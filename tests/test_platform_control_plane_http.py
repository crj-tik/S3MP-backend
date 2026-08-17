"""HTTP authorization coverage for platform control-plane read routes."""

from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from s3mp.common.config import Settings
from s3mp.main import create_app
from s3mp.platform.api.control_router import _codec, _platform_tenant, _query_scope
from s3mp.platform.domain.context import PlatformContext


class _ControlPlaneService:
    async def list_accounts(
        self, *_args: Any, **_kwargs: Any
    ) -> tuple[list[dict[str, object]], None]:
        return [], None

    async def get_account(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def list_roles(
        self, *_args: Any, **_kwargs: Any
    ) -> tuple[list[dict[str, object]], None]:
        return [], None

    async def list_role_bindings(
        self, *_args: Any, **_kwargs: Any
    ) -> tuple[list[dict[str, object]], None]:
        return [], None

    async def list_support(
        self, *_args: Any, **_kwargs: Any
    ) -> tuple[list[dict[str, object]], None]:
        return [], None

    async def get_support(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def list_audit(self, *_args: Any, **_kwargs: Any) -> tuple[list[dict[str, object]], None]:
        return [], None

    async def get_audit(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@pytest.mark.parametrize(
    ("path", "permission"),
    [
        ("/api/v1/platform/accounts", "platform.accounts.read"),
        (f"/api/v1/platform/accounts/{uuid4()}", "platform.accounts.read"),
        ("/api/v1/platform/roles", "platform.roles.read"),
        ("/api/v1/platform/role-bindings", "platform.roles.read"),
        ("/api/v1/platform/support-access", "platform.support.read"),
        (f"/api/v1/platform/support-access/{uuid4()}", "platform.support.read"),
        ("/api/v1/platform/audit-events", "platform.audit.read"),
        (f"/api/v1/platform/audit-events/{uuid4()}", "platform.audit.read"),
    ],
)
async def test_platform_read_routes_require_their_dedicated_permission(
    path: str, permission: str
) -> None:
    app = create_app(Settings())
    app.state.platform_control_plane = _ControlPlaneService()
    context = PlatformContext(uuid4(), uuid4(), frozenset({permission}))

    @app.middleware("http")
    async def inject_platform_context(request: Any, call_next: Any) -> Any:
        request.state.platform_context = context
        return await call_next(request)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code in {200, 404}


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/platform/accounts",
        f"/api/v1/platform/accounts/{uuid4()}",
        "/api/v1/platform/roles",
        "/api/v1/platform/role-bindings",
        "/api/v1/platform/support-access",
        f"/api/v1/platform/support-access/{uuid4()}",
        "/api/v1/platform/audit-events",
        f"/api/v1/platform/audit-events/{uuid4()}",
    ],
)
async def test_platform_read_routes_reject_missing_platform_permission(path: str) -> None:
    app = create_app(Settings())
    app.state.platform_control_plane = _ControlPlaneService()
    context = PlatformContext(uuid4(), uuid4(), frozenset())

    @app.middleware("http")
    async def inject_platform_context(request: Any, call_next: Any) -> Any:
        request.state.platform_context = context
        return await call_next(request)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_platform_list_filters_are_validated_and_cursors_are_filter_bound() -> None:
    app = create_app(Settings())
    app.state.platform_control_plane = _ControlPlaneService()
    context = PlatformContext(
        uuid4(), uuid4(), frozenset({"platform.accounts.read", "platform.support.read"})
    )

    @app.middleware("http")
    async def inject_platform_context(request: Any, call_next: Any) -> Any:
        request.state.platform_context = context
        return await call_next(request)

    active_cursor = _codec.encode(
        _platform_tenant,
        context.user_id,
        1,
        str(uuid4()),
        query=_query_scope("platform_accounts", query=None, status="active"),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid_status = await client.get("/api/v1/platform/accounts?status=unknown")
        mismatched_cursor = await client.get(
            "/api/v1/platform/accounts",
            params={"status": "disabled", "cursor": active_cursor},
        )
        invalid_support_status = await client.get("/api/v1/platform/support-access?status=unknown")

    assert invalid_status.status_code == 422
    assert mismatched_cursor.status_code == 400
    assert mismatched_cursor.json()["code"] == "invalid_cursor"
    assert invalid_support_status.status_code == 422
