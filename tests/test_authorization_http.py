"""HTTP contract tests for the authorization router (fake-service injection)."""

from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from _http import make_app
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext


def _ctx() -> PrincipalContext:
    return PrincipalContext(uuid4(), uuid4(), uuid4(), 1)


class FakeAuthorizationManagement:
    def __init__(self, *, cross_tenant_principal: bool = False) -> None:
        self.cross_tenant_principal = cross_tenant_principal

    async def list_groups(self, _ctx: PrincipalContext) -> list[dict[str, Any]]:
        return [{"id": "g1", "name": "engineers"}]

    async def create_group(self, _ctx: PrincipalContext, body: Any) -> dict[str, Any]:
        return {"id": "g-new", "name": body.name}

    async def get_group(self, _ctx: PrincipalContext, group_id: str) -> dict[str, Any]:
        return {"id": group_id, "name": "engineers"}

    async def update_group(
        self, _ctx: PrincipalContext, group_id: str, body: Any
    ) -> dict[str, Any]:
        return {"id": group_id, "name": body.name}

    async def delete_group(self, _ctx: PrincipalContext, group_id: str) -> None:
        return None

    async def list_roles(self, _ctx: PrincipalContext) -> list[dict[str, Any]]:
        return [{"id": "r1", "name": "viewer"}]

    async def create_role(self, _ctx: PrincipalContext, body: Any) -> dict[str, Any]:
        return {"id": "r-new", "name": body.name, "permissions": body.permissions}

    async def get_role(self, _ctx: PrincipalContext, role_id: str) -> dict[str, Any]:
        return {"id": role_id, "name": "viewer"}

    async def update_role(self, _ctx: PrincipalContext, role_id: str, body: Any) -> dict[str, Any]:
        return {"id": role_id, "name": body.name}

    async def list_role_bindings(
        self, _ctx: PrincipalContext, principal_id: str | None = None
    ) -> list[dict[str, Any]]:
        return [{"id": "b1", "principal_id": str(_ctx.principal_id), "effect": "allow"}]

    async def create_role_binding(self, _ctx: PrincipalContext, body: Any) -> dict[str, Any]:
        return {"id": "b-new", "principal_id": body.principal_id, "effect": body.effect}

    async def get_role_binding(
        self, _ctx: PrincipalContext, role_binding_id: str
    ) -> dict[str, Any]:
        return {"id": role_binding_id, "effect": "allow"}

    async def revoke_role_binding(self, _ctx: PrincipalContext, role_binding_id: str) -> None:
        return None

    async def get_effective_permissions(
        self,
        _ctx: PrincipalContext,
        principal_id: str,
        storage_space_id: str | None = None,
        object_key: str | None = None,
    ) -> dict[str, Any]:
        if self.cross_tenant_principal:
            raise ApiError("resource_not_found", "Principal not found", status_code=404)
        return {"principal_id": principal_id, "permissions": ["files.read"]}

    async def simulate_authorization(
        self,
        _ctx: PrincipalContext,
        principal_id: str,
        permission: str,
        storage_space_id: str | None = None,
        object_key: str | None = None,
    ) -> dict[str, Any]:
        return {
            "principal_id": principal_id,
            "permission": permission,
            "decision": "allow",
            "matched_sources": [],
            "reason": "default allow",
        }


async def test_list_groups_returns_200() -> None:
    ctx = _ctx()
    app = make_app({"authorization_management": FakeAuthorizationManagement()}, context=ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/groups")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "engineers"


async def test_create_role_binding_returns_201() -> None:
    ctx = _ctx()
    app = make_app({"authorization_management": FakeAuthorizationManagement()}, context=ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/role_bindings",
            json={
                "principal_id": str(ctx.principal_id),
                "role_id": "r1",
                "effect": "allow",
                "scope": {"type": "directory"},
                "reason": "initial",
                "expires_at": "2027-01-01T00:00:00Z",
            },
        )

    assert response.status_code == 201


async def test_get_effective_permissions_returns_permissions() -> None:
    ctx = _ctx()
    app = make_app({"authorization_management": FakeAuthorizationManagement()}, context=ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/principals/{ctx.principal_id}/effective_permissions"
        )

    assert response.status_code == 200
    assert response.json()["permissions"] == ["files.read"]


async def test_simulate_authorization_returns_decision() -> None:
    ctx = _ctx()
    app = make_app({"authorization_management": FakeAuthorizationManagement()}, context=ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/authorization/simulations",
            json={"principal_id": str(ctx.principal_id), "permission": "files.read"},
        )

    assert response.status_code == 200
    assert response.json()["decision"] == "allow"


async def test_unauthenticated_request_returns_401() -> None:
    app = make_app({"authorization_management": FakeAuthorizationManagement()})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/roles")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


async def test_cross_tenant_principal_effective_permissions_returns_404_without_leaking() -> None:
    ctx = _ctx()
    app = make_app(
        {"authorization_management": FakeAuthorizationManagement(cross_tenant_principal=True)},
        context=ctx,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/principals/{uuid4()}/effective_permissions")

    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"
    assert "id" not in response.json()
