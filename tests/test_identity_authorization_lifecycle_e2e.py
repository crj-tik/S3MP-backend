"""Production-wired identity and authorization management checks on PostgreSQL."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from _infrastructure import delete_tenant, real_session_factory, real_settings, seed_tenant
from s3mp.authorization.infrastructure.models import (
    PermissionModel,
    RoleBindingModel,
    RoleModel,
    RolePermissionModel,
)
from s3mp.identity.domain.context import PrincipalContext
from s3mp.identity.infrastructure.models import (
    MembershipModel,
    MembershipStatus,
    PrincipalModel,
    PrincipalType,
    SessionModel,
    UserModel,
)
from s3mp.main import create_app


async def _seed_admin(app: Any, tenant_id: UUID) -> PrincipalContext:
    factory = real_session_factory(app.state.engine)
    user_id, principal_id, membership_id, role_id = uuid4(), uuid4(), uuid4(), uuid4()
    permissions = [
        "members.read",
        "members.manage",
        "groups.read",
        "groups.manage",
        "roles.read",
        "roles.manage",
        "role_bindings.read",
        "role_bindings.manage",
        "authorization.explain",
        "authorization.simulate",
    ]
    async with factory() as session:
        session.add(
            UserModel(
                id=user_id,
                email=f"{user_id}@test",
                normalized_email=f"{user_id}@test",
                display_name="Admin",
            )
        )
        session.add(
            PrincipalModel(
                id=principal_id, tenant_id=tenant_id, type=PrincipalType.USER, display_name="Admin"
            )
        )
        await session.flush()
        session.add(
            MembershipModel(
                id=membership_id,
                tenant_id=tenant_id,
                user_id=user_id,
                principal_id=principal_id,
                status=MembershipStatus.ACTIVE,
            )
        )
        session.add(
            RoleModel(
                id=role_id, tenant_id=tenant_id, name=f"admin-{role_id}", description="test admin"
            )
        )
        await session.flush()
        rows = (
            await session.scalars(
                select(PermissionModel).where(PermissionModel.name.in_(permissions))
            )
        ).all()
        if len(rows) != len(permissions):
            for name in set(permissions) - {row.name for row in rows}:
                session.add(
                    PermissionModel(
                        name=name, resource_type="test", delegable=True, description="test"
                    )
                )
            await session.flush()
            rows = (
                await session.scalars(
                    select(PermissionModel).where(PermissionModel.name.in_(permissions))
                )
            ).all()
        session.add_all(
            [RolePermissionModel(role_id=role_id, permission_id=row.id) for row in rows]
        )
        session.add(
            RoleBindingModel(
                tenant_id=tenant_id,
                principal_id=principal_id,
                role_id=role_id,
                effect="allow",
                reason="test",
                starts_at=datetime.now(UTC) - timedelta(minutes=1),
                expires_at=datetime.now(UTC) + timedelta(days=1),
                created_by_principal_id=principal_id,
            )
        )
        await session.commit()
    return PrincipalContext(tenant_id, principal_id, membership_id, 1)


async def test_management_services_are_wired_and_execute_against_real_postgresql() -> None:
    app = create_app(real_settings())
    async with app.router.lifespan_context(app):
        assert app.state.identity_management is not None
        assert app.state.authorization_management is not None
        tenant_id = uuid4()
        await seed_tenant(app.state.engine, tenant_id)
        try:
            context = await _seed_admin(app, tenant_id)

            @app.middleware("http")
            async def inject(request: Any, call_next: Callable[[Any], Awaitable[Any]]) -> Any:
                request.state.principal_context = context
                return await call_next(request)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                me = await client.get("/api/v1/me")
                assert me.status_code == 200
                assert me.json()["principal"]["id"] == str(context.principal_id)

                role = await client.post(
                    "/api/v1/roles", json={"name": "reader", "permissions": ["members.read"]}
                )
                assert role.status_code == 201
                assert role.json()["permissions"] == ["members.read"]

                member = await client.post("/api/v1/members", json={"email": "member@example.test"})
                assert member.status_code == 201
                assert "tenant_id" not in member.json()

                group = await client.post("/api/v1/groups", json={"name": "reviewers"})
                assert group.status_code == 201
                group_body = group.json()
                assert group_body["principal"]["type"] == "group"
                added = await client.post(
                    f"/api/v1/groups/{group_body['id']}/members",
                    json={"membership_id": member.json()["id"]},
                )
                assert added.status_code == 204

                factory = real_session_factory(app.state.engine)
                async with factory() as session:
                    managed_member = await session.get(MembershipModel, member.json()["id"])
                    assert managed_member is not None
                    member_version = managed_member.authorization_version
                    session.add(
                        SessionModel(
                            tenant_id=tenant_id,
                            membership_id=managed_member.id,
                            principal_id=managed_member.principal_id,
                            token_digest=uuid4().bytes,
                            csrf_digest=uuid4().bytes,
                            authorization_version=member_version,
                            expires_at=datetime.now(UTC) + timedelta(hours=1),
                        )
                    )
                    await session.commit()

                binding = await client.post(
                    "/api/v1/role_bindings",
                    json={
                        "principal_id": group_body["principal"]["id"],
                        "role_id": role.json()["id"],
                        "effect": "allow",
                        "scope": {"type": "tenant"},
                        "reason": "review access",
                        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                    },
                )
                assert binding.status_code == 201
                assert binding.json()["principal"] == group_body["principal"]

                async with factory() as session:
                    refreshed_member = await session.get(MembershipModel, member.json()["id"])
                    revoked_session = await session.scalar(
                        select(SessionModel).where(
                            SessionModel.membership_id == member.json()["id"]
                        )
                    )
                    assert refreshed_member is not None
                    assert refreshed_member.authorization_version == member_version + 1
                    assert revoked_session is not None and revoked_session.revoked_at is not None

                simulation = await client.post(
                    "/api/v1/authorization/simulations",
                    json={"principal_id": str(context.principal_id), "permission": "members.read"},
                )
                assert simulation.status_code == 200
                assert simulation.json()["decision"] == "allow"

                explained = await client.get(
                    f"/api/v1/principals/{context.principal_id}/effective_permissions"
                )
                assert explained.status_code == 200
                assert any(
                    item["permission"] == "roles.manage" for item in explained.json()["permissions"]
                )
        finally:
            await delete_tenant(app.state.engine, tenant_id)


async def test_management_routes_fail_closed_without_database_services() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/roles")
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
