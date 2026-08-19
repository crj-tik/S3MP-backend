"""HTTP contract tests for platform quota allocation routes."""

from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from s3mp.common.config import Settings
from s3mp.main import create_app
from s3mp.platform.domain.context import PlatformContext


def _app(service: Any, *, permissions: set[str]) -> FastAPI:
    app = create_app(Settings())
    app.state.platform_quota_service = service
    context = PlatformContext(uuid4(), uuid4(), frozenset(permissions))

    @app.middleware("http")
    async def inject(request: Any, call_next: Any) -> Any:
        request.state.platform_context = context
        return await call_next(request)

    return app


class FakePlatformQuotaService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def list_quotas(self, _context: Any, **_kwargs: Any) -> tuple[list[dict[str, Any]], None]:
        self.calls.append("list")
        return ([{"id": str(uuid4()), "limit_bytes": 100, "status": "active"}], None)

    async def create_quota(self, _context: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("create")
        return {
            "id": str(uuid4()),
            **{
                key: str(value) if key in {"tenant_id", "application_id"} and value else value
                for key, value in kwargs.items()
            },
            "status": "active",
        }


async def test_platform_quota_list_is_typed_and_paginated() -> None:
    service = FakePlatformQuotaService()
    app = _app(service, permissions={"platform.quotas.read"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/platform/quotas?status=active")

    assert response.status_code == 200
    assert response.json()["items"][0]["limit_bytes"] == 100
    assert response.json()["next_cursor"] is None
    assert service.calls == ["list"]


async def test_platform_quota_create_requires_manage_permission() -> None:
    service = FakePlatformQuotaService()
    app = _app(service, permissions={"platform.quotas.read"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/platform/quotas",
            json={"tenant_id": str(uuid4()), "limit_gib": 1},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert service.calls == []


async def test_platform_quota_create_returns_tenant_scope() -> None:
    service = FakePlatformQuotaService()
    app = _app(service, permissions={"platform.quotas.manage"})
    tenant_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/platform/quotas",
            json={"tenant_id": str(tenant_id), "limit_gib": 1},
        )

    assert response.status_code == 201
    assert response.json()["tenant_id"] == str(tenant_id)
    assert service.calls == ["create"]


async def test_platform_quota_rejects_legacy_byte_input() -> None:
    service = FakePlatformQuotaService()
    app = _app(service, permissions={"platform.quotas.manage"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/platform/quotas",
            json={"tenant_id": str(uuid4()), "limit_bytes": 1073741824},
        )

    assert response.status_code == 422
    assert service.calls == []
