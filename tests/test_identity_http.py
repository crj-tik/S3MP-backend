"""HTTP contract tests for the identity router (fake-service injection)."""

from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from _http import make_app
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext
from s3mp.main import create_app


def _ctx() -> PrincipalContext:
    return PrincipalContext(uuid4(), uuid4(), uuid4(), 1)


class FakeIdentityManagement:
    def __init__(self, *, cross_tenant_member: bool = False) -> None:
        self.cross_tenant_member = cross_tenant_member

    async def list_users(self, _ctx: PrincipalContext) -> list[dict[str, Any]]:
        return [{"id": str(_ctx.principal_id), "display_name": "U"}]

    async def get_user(self, _ctx: PrincipalContext, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "display_name": "U"}

    async def list_members(self, _ctx: PrincipalContext) -> list[dict[str, Any]]:
        return [{"id": str(_ctx.membership_id), "status": "active"}]

    async def create_member(self, _ctx: PrincipalContext, body: Any) -> dict[str, Any]:
        return {"id": str(uuid4()), "email": body.email, "status": "active"}

    async def get_member(self, _ctx: PrincipalContext, membership_id: str) -> dict[str, Any]:
        if self.cross_tenant_member:
            raise ApiError("resource_not_found", "Member not found", status_code=404)
        return {"id": membership_id, "status": "active"}

    async def update_member(
        self, _ctx: PrincipalContext, membership_id: str, body: Any
    ) -> dict[str, Any]:
        return {"id": membership_id, "status": body.status}

    async def list_group_members(
        self, _ctx: PrincipalContext, group_id: str
    ) -> list[dict[str, Any]]:
        return [{"id": str(_ctx.membership_id)}]

    async def add_group_member(
        self, _ctx: PrincipalContext, group_id: str, membership_id: str
    ) -> None:
        return None

    async def remove_group_member(
        self, _ctx: PrincipalContext, group_id: str, membership_id: str
    ) -> None:
        return None


class FakeContextProvider:
    async def get_me(self, ctx: PrincipalContext) -> dict[str, Any]:
        return {
            "principal": {"id": str(ctx.principal_id), "type": "user", "display_name": "U"},
            "current_tenant": {
                "id": str(ctx.tenant_id), "name": "T", "membership_status": "active",
            },
            "available_tenants": [],
            "coarse_permissions": ["files.read"],
            "authorization_version": ctx.authorization_version,
        }


async def test_get_me_returns_server_derived_context() -> None:
    ctx = _ctx()
    app = make_app(
        {
            "identity_context_provider": FakeContextProvider(),
            "identity_management": FakeIdentityManagement(),
        },
        context=ctx,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/me")

    assert response.status_code == 200
    body = response.json()
    assert body["principal"]["id"] == str(ctx.principal_id)
    assert body["authorization_version"] == 1


async def test_list_users_returns_principal_scoped_results() -> None:
    ctx = _ctx()
    app = make_app(
        {
            "identity_context_provider": FakeContextProvider(),
            "identity_management": FakeIdentityManagement(),
        },
        context=ctx,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/users")

    assert response.status_code == 200
    assert response.json()[0]["id"] == str(ctx.principal_id)


async def test_create_member_returns_201() -> None:
    ctx = _ctx()
    app = make_app(
        {
            "identity_context_provider": FakeContextProvider(),
            "identity_management": FakeIdentityManagement(),
        },
        context=ctx,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/members", json={"email": "new@example.test"})

    assert response.status_code == 201
    assert response.json()["email"] == "new@example.test"


async def test_unauthenticated_request_returns_401() -> None:
    app = create_app()
    app.state.identity_context_provider = FakeContextProvider()
    app.state.identity_management = FakeIdentityManagement()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


async def test_cross_tenant_member_returns_404_without_leaking() -> None:
    ctx = _ctx()
    app = make_app(
        {"identity_context_provider": FakeContextProvider(),
         "identity_management": FakeIdentityManagement(cross_tenant_member=True)},
        context=ctx,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/members/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"
    assert "id" not in response.json()
