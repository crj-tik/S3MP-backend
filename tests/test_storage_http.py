"""HTTP contract tests for the storage router (fake-service injection)."""

from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from _http import make_app
from s3mp.identity.domain.context import PrincipalContext


def _ctx() -> PrincipalContext:
    return PrincipalContext(uuid4(), uuid4(), uuid4(), 1)


class FakeStorageService:
    async def list_connections(self, tenant_id: Any) -> list[dict[str, Any]]:
        return [{"id": str(uuid4()), "name": "primary", "status": "active"}]

    async def get_connection(self, tenant_id: Any, conn_id: str) -> dict[str, Any]:
        return {"id": conn_id, "name": "primary", "status": "active"}

    async def create_connection(self, tenant_id: Any, body: Any) -> dict[str, Any]:
        return {
            "id": str(uuid4()),
            "name": body.name,
            "endpoint": body.endpoint,
            "status": "active",
        }

    async def probe_connection(
        self, tenant_id: Any, conn_id: str, write_test_prefix: str | None
    ) -> dict[str, Any]:
        return {"connection_id": conn_id, "reachable": True, "writable": True}

    async def list_spaces(self, tenant_id: Any) -> list[dict[str, Any]]:
        return [{"id": str(uuid4()), "name": "default", "bucket": "s3mp-dev"}]

    async def get_space(self, tenant_id: Any, space_id: str) -> dict[str, Any]:
        return {"id": space_id, "name": "default", "bucket": "s3mp-dev"}

    async def create_space(self, tenant_id: Any, body: Any) -> dict[str, Any]:
        return {"id": str(uuid4()), "name": body.name, "bucket": body.bucket}


def _app() -> Any:
    return make_app({"storage_service": FakeStorageService()}, context=_ctx())


async def test_list_storage_connections_returns_200() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/storage_connections")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "primary"


async def test_create_storage_connection_returns_201() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/storage_connections",
            json={
                "name": "primary",
                "endpoint": "https://s3.example.com",
                "region": "us-east-1",
                "path_style": True,
                "credential_reference": "vault/s3/primary",
            },
        )

    assert response.status_code == 201
    assert response.json()["endpoint"] == "https://s3.example.com"


async def test_get_storage_space_returns_200() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/storage_spaces/{uuid4()}")

    assert response.status_code == 200
    assert response.json()["bucket"] == "s3mp-dev"


async def test_unauthenticated_request_returns_401() -> None:
    app = make_app({"storage_service": FakeStorageService()})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/storage_connections")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
