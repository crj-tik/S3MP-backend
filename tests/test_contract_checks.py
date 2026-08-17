"""Tests for the OpenAPI contract validation script's forward and reverse checks.

These tests verify the ``main()`` comparison logic by constructing synthetic
baselines from the runtime OpenAPI schema. They do NOT depend on the committed
``contracts/openapi.yaml`` matching the runtime (which is a separate concern).

NOTE: ``scripts/check_openapi.py`` currently exits 1 against the committed
baseline because ``contracts/openapi.yaml`` paths lack the ``/api/v1`` prefix
that the runtime routers register. That drift is reported separately and is
not asserted here.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.check_openapi as check_openapi  # noqa: E402


def _runtime_openapi() -> dict[str, Any]:
    from s3mp.main import app

    return app.openapi()


def _write_baseline(tmp_path: Path, document: dict[str, Any]) -> Path:
    baseline_file = tmp_path / "baseline.yaml"
    baseline_file.write_text(yaml.safe_dump(document), encoding="utf-8")
    return baseline_file


def test_main_returns_0_when_baseline_matches_runtime(tmp_path: Path) -> None:
    """A baseline identical to the runtime surface must pass."""
    baseline = copy.deepcopy(_runtime_openapi())
    baseline_file = _write_baseline(tmp_path, baseline)

    original = check_openapi.BASELINE
    check_openapi.BASELINE = baseline_file
    try:
        assert check_openapi.main() == 0
    finally:
        check_openapi.BASELINE = original


def test_reverse_check_fails_when_baseline_has_extra_endpoint(tmp_path: Path) -> None:
    """A baseline endpoint absent from runtime must fail the reverse check."""
    baseline = copy.deepcopy(_runtime_openapi())
    baseline["paths"]["/api/v1/nonexistent"] = {
        "get": {"operationId": "nonexistent_op", "responses": {"200": {"description": "x"}}}
    }
    baseline_file = _write_baseline(tmp_path, baseline)

    original = check_openapi.BASELINE
    check_openapi.BASELINE = baseline_file
    try:
        assert check_openapi.main() == 1
    finally:
        check_openapi.BASELINE = original


def test_forward_check_fails_when_baseline_lacks_runtime_endpoint(tmp_path: Path) -> None:
    """A runtime endpoint absent from the baseline must fail the forward check."""
    baseline = copy.deepcopy(_runtime_openapi())
    # Remove a non-health path that has at least one operation.
    assert "/api/v1/applications" in baseline["paths"]
    del baseline["paths"]["/api/v1/applications"]
    baseline_file = _write_baseline(tmp_path, baseline)

    original = check_openapi.BASELINE
    check_openapi.BASELINE = baseline_file
    try:
        assert check_openapi.main() == 1
    finally:
        check_openapi.BASELINE = original


def test_schema_check_fails_for_nested_success_response_drift(tmp_path: Path) -> None:
    """Strict management schemas reject deleted nested DTO properties."""
    baseline = copy.deepcopy(_runtime_openapi())
    del baseline["components"]["schemas"]["MembershipResponse"]["properties"]["principal"]
    baseline_file = _write_baseline(tmp_path, baseline)

    original = check_openapi.BASELINE
    check_openapi.BASELINE = baseline_file
    try:
        assert check_openapi.main() == 1
    finally:
        check_openapi.BASELINE = original


def test_operation_permission_classification_check_rejects_contract_drift() -> None:
    from scripts.check_contracts import validate_operation_permission_classifications

    baseline = copy.deepcopy(_runtime_openapi())
    baseline["paths"]["/api/v1/roles"]["get"]["x-permission"] = "roles.manage"

    assert validate_operation_permission_classifications(baseline)


def test_management_route_enforcement_check_accepts_current_routes() -> None:
    from scripts.check_contracts import validate_management_route_enforcement

    assert validate_management_route_enforcement() == []


def test_platform_control_plane_operations_have_explicit_success_schemas() -> None:
    document = _runtime_openapi()
    operations = {
        operation.get("operationId"): operation
        for path in document["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and operation.get("operationId")
    }
    for operation_id in (
        "list_platform_accounts",
        "list_platform_roles",
        "list_platform_role_bindings",
        "list_support_access",
        "list_platform_audit_events",
    ):
        response = operations[operation_id]["responses"]["200"]
        schema = response["content"]["application/json"]["schema"]
        assert schema["$ref"].startswith("#/components/schemas/")


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/users",
        "/api/v1/groups",
        "/api/v1/applications",
        "/api/v1/api_keys/00000000-0000-0000-0000-000000000001",
        "/api/v1/storage_connections",
        "/api/v1/quotas",
        "/api/v1/audit_events",
    ],
)
async def test_api_key_is_rejected_for_each_management_category(path: str) -> None:
    """Management denial is operation classification based, not URL-prefix based."""
    from uuid import uuid4

    from _http import make_app
    from s3mp.identity.domain.context import PrincipalContext

    context = PrincipalContext.for_application(uuid4(), uuid4(), application_id=uuid4())
    app = make_app(context=context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
