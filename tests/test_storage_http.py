"""HTTP contract tests for the storage router (fake-service injection)."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from _http import make_app
from s3mp.identity.domain.context import PrincipalContext


def _ctx() -> PrincipalContext:
    return PrincipalContext(uuid4(), uuid4(), uuid4(), 1)


class FakeStorageService:
    def __init__(self) -> None:
        self.calls = 0

    async def list_connections(
        self, tenant_id: Any, cursor: str | None = None, **_: Any
    ) -> tuple[list[dict[str, Any]], str | None]:
        self.calls += 1
        return ([{"id": str(uuid4()), "name": "primary", "status": "active"}], None)

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

    async def list_spaces(
        self, context: Any, cursor: str | None = None, **_: Any
    ) -> tuple[list[dict[str, Any]], str | None]:
        return (
            [
                {
                    "id": str(uuid4()),
                    "tenant_id": str(context.tenant_id),
                    "connection_id": str(uuid4()),
                    "name": "default",
                    "bucket": "s3mp-dev",
                    "root_prefix": "",
                    "provider_target_version": 1,
                    "status": "active",
                    "created_at": datetime.now(UTC).isoformat(),
                }
            ],
            None,
        )

    async def get_space(self, tenant_id: Any, space_id: str) -> dict[str, Any]:
        return {
            "id": space_id,
            "tenant_id": str(tenant_id.tenant_id),
            "connection_id": str(uuid4()),
            "name": "default",
            "bucket": "s3mp-dev",
            "root_prefix": "",
            "provider_target_version": 1,
            "status": "active",
            "created_at": datetime.now(UTC).isoformat(),
        }

    async def create_space(self, tenant_id: Any, body: Any) -> dict[str, Any]:
        return {
            "id": str(uuid4()),
            "tenant_id": str(tenant_id.tenant_id),
            "connection_id": str(uuid4()),
            "application_id": str(body.application_id),
            "name": body.name,
            "bucket": "s3mp-dev",
            "root_prefix": "",
            "storage_namespace": f"tenant/{body.application_id}",
            "profile_version": 1,
            "provider_target_version": 1,
            "status": "active",
            "created_at": datetime.now(UTC).isoformat(),
        }


class DenyingAuthorizationManagement:
    async def require_permission(self, _context: PrincipalContext, _permission: str) -> None:
        from s3mp.common.errors import ApiError

        raise ApiError("permission_denied", "Permission denied", status_code=403)


def _app() -> Any:
    return make_app({"storage_service": FakeStorageService()}, context=_ctx())


async def test_list_storage_connections_returns_200() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/storage_connections")

    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "primary"


async def test_create_storage_connection_is_removed_after_shared_profile_cutover() -> None:
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

    assert response.status_code == 405


async def test_get_storage_space_returns_200() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/storage_spaces/{uuid4()}")

    assert response.status_code == 200
    assert response.json()["bucket"] == "s3mp-dev"


async def test_list_storage_spaces_returns_page() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/storage_spaces")

    assert response.status_code == 200
    assert response.json()["items"][0]["bucket"] == "s3mp-dev"
    assert response.json()["next_cursor"] is None


async def test_create_storage_space_accepts_only_application_binding() -> None:
    app = _app()
    application_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/storage_spaces",
            json={"name": "应用存储", "application_id": str(application_id)},
        )

    assert response.status_code == 201
    assert response.json()["application_id"] == str(application_id)
    assert response.json()["bucket"] == "s3mp-dev"


async def test_create_storage_space_rejects_legacy_physical_target_fields() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/storage_spaces",
            json={
                "name": "应用存储",
                "application_id": str(uuid4()),
                "bucket": "tenant-controlled-bucket",
            },
        )

    assert response.status_code == 422


async def test_unauthenticated_request_returns_401() -> None:
    app = make_app({"storage_service": FakeStorageService()})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/storage_connections")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


async def test_api_key_cannot_call_storage_management_before_service() -> None:
    service = FakeStorageService()
    context = PrincipalContext.for_application(uuid4(), uuid4(), application_id=uuid4())
    app = make_app({"storage_service": service}, context=context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/storage_connections")

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    assert service.calls == 0


async def test_human_without_permission_cannot_call_storage_management_before_service() -> None:
    service = FakeStorageService()
    app = make_app(
        {"storage_service": service, "authorization_management": DenyingAuthorizationManagement()},
        context=_ctx(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/storage_connections")

    assert response.status_code == 403
    assert service.calls == 0
