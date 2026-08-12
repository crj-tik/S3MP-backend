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

    async def require_permission(self, _ctx: PrincipalContext, _permission: str) -> None:
        return None

    async def list_groups(
        self, _ctx: PrincipalContext, **_page: Any
    ) -> tuple[list[dict[str, Any]], None]:
        return ([self._group(_ctx, "g1")], None)

    async def create_group(self, _ctx: PrincipalContext, body: Any) -> dict[str, Any]:
        return self._group(_ctx, "g-new", body.name, body.description)

    async def get_group(self, _ctx: PrincipalContext, group_id: str) -> dict[str, Any]:
        return self._group(_ctx, group_id)

    async def update_group(
        self, _ctx: PrincipalContext, group_id: str, body: Any
    ) -> dict[str, Any]:
        return self._group(_ctx, group_id, body.name, body.description)

    async def delete_group(self, _ctx: PrincipalContext, group_id: str) -> None:
        return None

    async def list_roles(
        self, _ctx: PrincipalContext, **_page: Any
    ) -> tuple[list[dict[str, Any]], None]:
        return (
            [
                {
                    "id": "r1",
                    "name": "viewer",
                    "description": "",
                    "permissions": [],
                    "system": False,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "etag": "x",
                }
            ],
            None,
        )

    async def create_role(self, _ctx: PrincipalContext, body: Any) -> dict[str, Any]:
        return {
            "id": "r-new",
            "name": body.name,
            "description": body.description or "",
            "permissions": body.permissions,
            "system": False,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "etag": "x",
        }

    async def get_role(self, _ctx: PrincipalContext, role_id: str) -> dict[str, Any]:
        return {
            "id": role_id,
            "name": "viewer",
            "description": "",
            "permissions": [],
            "system": False,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "etag": "x",
        }

    async def update_role(self, _ctx: PrincipalContext, role_id: str, body: Any) -> dict[str, Any]:
        return {
            "id": role_id,
            "name": body.name,
            "description": body.description or "",
            "permissions": body.permissions,
            "system": False,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "etag": "x",
        }

    async def list_role_bindings(
        self, _ctx: PrincipalContext, principal_id: Any = None, **_page: Any
    ) -> tuple[list[dict[str, Any]], None]:
        return ([self._binding(_ctx)], None)

    async def create_role_binding(self, _ctx: PrincipalContext, body: Any) -> dict[str, Any]:
        return self._binding(_ctx, "b-new")

    async def get_role_binding(
        self, _ctx: PrincipalContext, role_binding_id: str
    ) -> dict[str, Any]:
        return self._binding(_ctx, role_binding_id)

    async def revoke_role_binding(self, _ctx: PrincipalContext, role_binding_id: str) -> None:
        return None

    async def get_effective_permissions(
        self, _ctx: PrincipalContext, principal_id: Any, *_args: Any
    ) -> dict[str, Any]:
        if self.cross_tenant_principal:
            raise ApiError("resource_not_found", "Principal not found", status_code=404)
        return {
            "principal_id": str(principal_id),
            "authorization_version": 1,
            "evaluated_at": "2026-01-01T00:00:00Z",
            "permissions": [
                {
                    "permission": "files.read",
                    "decision": "allow",
                    "reason_code": "binding_allow",
                    "sources": [],
                }
            ],
        }

    async def simulate_authorization(self, _ctx: PrincipalContext, body: Any) -> dict[str, Any]:
        return {
            "permission": body.permission,
            "decision": "allow",
            "reason_code": "binding_allow",
            "authorization_version": 1,
            "evaluated_at": "2026-01-01T00:00:00Z",
            "sources": [],
        }

    @staticmethod
    def _group(
        ctx: PrincipalContext,
        group_id: str,
        name: str = "engineers",
        description: str | None = None,
    ) -> dict[str, Any]:
        return {
            "id": group_id,
            "principal": {"id": str(uuid4()), "type": "group", "display_name": name},
            "name": name,
            "description": description or "",
            "member_count": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "etag": "x",
        }

    @staticmethod
    def _binding(ctx: PrincipalContext, binding_id: str = "b1") -> dict[str, Any]:
        return {
            "id": binding_id,
            "principal": {"id": str(ctx.principal_id), "type": "user", "display_name": "U"},
            "role_id": "r1",
            "effect": "allow",
            "scope": {"type": "tenant", "storage_space_id": None, "canonical_prefix": None},
            "reason": "test",
            "starts_at": "2026-01-01T00:00:00Z",
            "expires_at": "2027-01-01T00:00:00Z",
            "created_by": str(ctx.principal_id),
            "created_at": "2026-01-01T00:00:00Z",
            "etag": "x",
        }


class DenyingAuthorizationManagement(FakeAuthorizationManagement):
    async def require_permission(self, _ctx: PrincipalContext, _permission: str) -> None:
        raise ApiError("permission_denied", "Permission denied", status_code=403)


async def test_list_groups_returns_200() -> None:
    ctx = _ctx()
    app = make_app({"authorization_management": FakeAuthorizationManagement()}, context=ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/groups")

    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "engineers"


async def test_create_role_binding_returns_201() -> None:
    ctx = _ctx()
    app = make_app({"authorization_management": FakeAuthorizationManagement()}, context=ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/role_bindings",
            json={
                "principal_id": str(ctx.principal_id),
                "role_id": str(uuid4()),
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
        response = await client.get(f"/api/v1/principals/{ctx.principal_id}/effective_permissions")

    assert response.status_code == 200
    assert response.json()["permissions"][0]["permission"] == "files.read"


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


async def test_unauthorized_management_request_returns_403_before_target_lookup() -> None:
    ctx = _ctx()
    app = make_app({"authorization_management": DenyingAuthorizationManagement()}, context=ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/roles/{uuid4()}")

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_management_update_requires_if_match() -> None:
    ctx = _ctx()
    app = make_app({"authorization_management": FakeAuthorizationManagement()}, context=ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(f"/api/v1/groups/{uuid4()}", json={"name": "reviewers"})

    assert response.status_code == 428
    assert response.json()["code"] == "etag_required"


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
