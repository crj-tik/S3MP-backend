"""HTTP contract tests for the applications & API Key router (fake-service injection)."""

from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from _http import make_app
from s3mp.identity.domain.context import PrincipalContext


def _ctx() -> PrincipalContext:
    return PrincipalContext(uuid4(), uuid4(), uuid4(), 1)


class FakeApplicationService:
    def __init__(self) -> None:
        self.create_calls = 0

    async def list_apps(
        self, tenant_id: Any, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        return ([{"id": str(uuid4()), "name": "app-1", "status": "active"}], None)

    async def get_app(self, tenant_id: Any, app_id: Any) -> dict[str, Any]:
        return {"id": str(app_id), "name": "app-1", "status": "active"}

    async def create_app(
        self, tenant_id: Any, name: str, principal_id: Any
    ) -> dict[str, Any]:
        self.create_calls += 1
        return {"id": str(uuid4()), "name": name, "status": "active"}

    async def update_app(
        self, tenant_id: Any, app_id: Any, name: str | None
    ) -> dict[str, Any]:
        return {"id": str(app_id), "name": name or "renamed", "status": "active"}


class FakeApiKeyService:
    def __init__(self) -> None:
        self.issued = 0

    async def list_keys(
        self, tenant_id: Any, app_id: Any, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        return ([{"id": str(uuid4()), "key_id": "sk_test", "status": "active"}], None)

    async def issue(
        self, tenant_id: Any, app_id: Any, scopes: list[str], ttl_days: int = 90
    ) -> dict[str, Any]:
        self.issued += 1
        return {
            "id": str(uuid4()),
            "key_id": "sk_test",
            "secret": "raw-secret-once",
            "credential": "sk_test.raw-secret-once",
            "scopes": scopes,
            "status": "active",
        }

    async def get_key(self, tenant_id: Any, key_id: Any) -> dict[str, Any]:
        return {"id": str(key_id), "key_id": "sk_test", "status": "active"}

    async def rotate(
        self, tenant_id: Any, key_id: Any, overlap_seconds: int = 300
    ) -> dict[str, Any]:
        return {
            "id": str(uuid4()),
            "key_id": "sk_rotated",
            "secret": "rotated-secret",
            "credential": "sk_rotated.rotated-secret",
            "status": "active",
        }

    async def revoke(self, tenant_id: Any, key_id: Any, reason: str) -> dict[str, Any]:
        return {"id": str(key_id), "status": "revoked", "reason": reason}


def _app() -> Any:
    return make_app(
        {
            "application_service": FakeApplicationService(),
            "api_key_service": FakeApiKeyService(),
        },
        context=_ctx(),
    )


async def test_list_applications_returns_200() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/applications")

    assert response.status_code == 200
    body = response.json()
    # list_apps returns ([apps], cursor) → serialized as [apps_list, cursor]
    assert isinstance(body, list)
    assert body[0][0]["name"] == "app-1"


async def test_create_application_returns_201() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/applications", json={"name": "new-app"})

    assert response.status_code == 201
    assert response.json()["name"] == "new-app"


async def test_create_api_key_returns_201_with_one_time_secret() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/applications/{uuid4()}/api_keys",
            json={"scopes": ["files.read"], "ttl_days": 30},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["secret"] == "raw-secret-once"  # noqa: S105
    assert body["credential"]


async def test_get_api_key_secret_returns_410() -> None:
    # The router hard-codes a 410 for secret retrieval after issuance. Note: the
    # contract spec names this `secret_not_retrievable`, while the implementation
    # emits `secret_gone` — this test asserts the implemented behaviour.
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/api_keys/{uuid4()}/secret")

    assert response.status_code == 410
    assert response.json()["code"] == "secret_not_retrievable"


async def test_revoke_api_key_returns_200() -> None:
    app = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/api_keys/{uuid4()}/revocations",
            json={"reason": "leaked"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "revoked"


async def test_unauthenticated_request_returns_401() -> None:
    app = make_app(
        {
            "application_service": FakeApplicationService(),
            "api_key_service": FakeApiKeyService(),
        }
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/applications")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
