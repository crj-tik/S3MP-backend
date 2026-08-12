"""HTTP contract tests for the governance (quota & audit) router (fake-service injection)."""

from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from _http import make_app
from s3mp.identity.domain.context import PrincipalContext


def _ctx() -> PrincipalContext:
    return PrincipalContext(uuid4(), uuid4(), uuid4(), 1)


class FakeQuotaService:
    async def list_quotas(
        self, tenant_id: Any, storage_space_id: str | None = None
    ) -> list[dict[str, Any]]:
        return [{"id": str(uuid4()), "limit_bytes": 1073741824, "used_bytes": 0}]

    async def get_quota(self, tenant_id: Any, quota_id: Any) -> dict[str, Any]:
        return {"id": str(quota_id), "limit_bytes": 1073741824, "used_bytes": 0}

    async def update_quota(
        self, tenant_id: Any, quota_id: Any, limit_bytes: int
    ) -> dict[str, Any]:
        return {"id": str(quota_id), "limit_bytes": limit_bytes, "used_bytes": 0}


class FakeAuditService:
    async def list_audit_events(
        self,
        tenant_id: Any,
        *,
        occurred_from: str | None = None,
        occurred_to: str | None = None,
        action: str | None = None,
        actor_principal_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return [{"id": str(uuid4()), "action": "file.upload", "resource_type": "file_object"}]

    async def get_audit_event(self, tenant_id: Any, audit_event_id: Any) -> dict[str, Any]:
        return {"id": str(audit_event_id), "action": "file.upload"}


def _app() -> Any:
    return make_app(
        {"quota_service": FakeQuotaService(), "audit_service": FakeAuditService()},
        context=_ctx(),
    )


async def test_list_quotas_returns_200() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/quotas")

    assert response.status_code == 200
    assert response.json()[0]["limit_bytes"] == 1073741824


async def test_update_quota_returns_200() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            f"/api/v1/quotas/{uuid4()}", json={"limit_bytes": 2147483648}
        )

    assert response.status_code == 200
    assert response.json()["limit_bytes"] == 2147483648


async def test_list_audit_events_returns_200() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/audit_events")

    assert response.status_code == 200
    assert response.json()[0]["action"] == "file.upload"


async def test_unauthenticated_request_returns_401() -> None:
    app = make_app(
        {"quota_service": FakeQuotaService(), "audit_service": FakeAuditService()}
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/quotas")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
