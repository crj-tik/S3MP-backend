"""Repository verification for platform authority lifecycle boundaries."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from _infrastructure import delete_tenant, real_engine, real_session_factory, seed_tenant
from s3mp.authorization.infrastructure.models import RoleBindingModel
from s3mp.identity.infrastructure.models import (
    MembershipModel,
    MembershipStatus,
    UserModel,
    UserStatus,
)
from s3mp.platform.infrastructure.models import (
    PlatformAuditEventModel,
    PlatformBootstrapStateModel,
    PlatformRoleModel,
    SupportAccessRequestModel,
    TenantLifecycleStatus,
)
from s3mp.platform.infrastructure.repository import SqlAlchemyPlatformStore
from s3mp.platform.scheduler import expire_once
from s3mp.tenant.infrastructure.models import TenantModel


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    connection = real_engine()
    yield connection
    await connection.dispose()


async def _delete_users(store: SqlAlchemyPlatformStore, *user_ids: UUID) -> None:
    """Remove only rows created by these tests, including immutable audit rows."""
    async with store.session_factory.begin() as session:
        await session.execute(
            delete(PlatformAuditEventModel).where(
                PlatformAuditEventModel.actor_user_id.in_(user_ids)
            )
        )
        await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))


async def test_bootstrap_can_create_only_one_platform_administrator(engine: AsyncEngine) -> None:
    store = SqlAlchemyPlatformStore(real_session_factory(engine))
    async with store.session_factory() as session:
        if await session.get(PlatformBootstrapStateModel, True) is not None:
            pytest.skip("the local environment has already been bootstrapped")

    suffix = uuid4().hex
    first_user_id: UUID | None = None
    try:
        first_user_id = await store.create_initial_platform_admin(
            email=f"bootstrap-{suffix}@example.test",
            employee_number=f"BOOT-{suffix[:8]}",
            display_name="Bootstrap test",
            password_hash="test-hash",  # noqa: S106 - no credential is persisted after the test
        )
        with pytest.raises(ValueError, match="already exists"):
            await store.create_initial_platform_admin(
                email=f"second-{suffix}@example.test",
                employee_number=f"SECOND-{suffix[:8]}",
                display_name="Second bootstrap test",
                password_hash="test-hash",  # noqa: S106 - no credential is persisted after the test
            )
    finally:
        async with store.session_factory.begin() as session:
            if first_user_id is not None:
                await session.execute(
                    delete(PlatformAuditEventModel).where(
                        PlatformAuditEventModel.actor_user_id == first_user_id
                    )
                )
                await session.execute(delete(UserModel).where(UserModel.id == first_user_id))
            await session.execute(delete(PlatformBootstrapStateModel))


async def test_tenant_creation_rejects_invalid_initial_admin_without_partial_tenant(
    engine: AsyncEngine,
) -> None:
    store = SqlAlchemyPlatformStore(real_session_factory(engine))
    user_id, actor_id, suffix = uuid4(), uuid4(), uuid4().hex
    async with store.session_factory.begin() as session:
        for current_id, label in ((user_id, "Disabled"), (actor_id, "Actor")):
            email = f"{current_id}@example.test"
            session.add(
                UserModel(
                    id=current_id,
                    email=email,
                    normalized_email=email,
                    display_name=label,
                    status=UserStatus.DISABLED if current_id == user_id else UserStatus.ACTIVE,
                )
            )
    try:
        with pytest.raises(ValueError, match="active account"):
            await store.create_platform_tenant(
                slug=f"atomic-{suffix}",
                name="Atomic test",
                initial_admin_user_id=user_id,
                actor_user_id=actor_id,
            )
        async with store.session_factory() as session:
            assert (
                await session.scalar(
                    select(TenantModel.id).where(TenantModel.slug == f"atomic-{suffix}")
                )
                is None
            )
            assert (
                await session.scalar(
                    select(MembershipModel.id).where(MembershipModel.user_id == user_id)
                )
                is None
            )
    finally:
        await _delete_users(store, user_id, actor_id)


async def test_platform_management_workflow_discovers_and_closes_control_plane_records(
    engine: AsyncEngine,
) -> None:
    store = SqlAlchemyPlatformStore(real_session_factory(engine))
    actor_id, initial_admin_id, target_id, approver_id = (uuid4() for _ in range(4))
    suffix = uuid4().hex
    tenant_id: UUID | None = None
    async with store.session_factory.begin() as session:
        for current_id, label in (
            (actor_id, "Actor"),
            (initial_admin_id, "Initial admin"),
            (target_id, "Target"),
            (approver_id, "Approver"),
        ):
            email = f"{current_id}@example.test"
            session.add(
                UserModel(
                    id=current_id,
                    email=email,
                    normalized_email=email,
                    display_name=label,
                    status=UserStatus.ACTIVE,
                )
            )
    try:
        accounts, _ = await store.list_platform_accounts(
            limit=10,
            cursor=None,
            query=f"{initial_admin_id}@example.test",
            status="active",
        )
        assert len(accounts) == 1 and accounts[0]["id"] == initial_admin_id

        tenant = await store.create_platform_tenant(
            slug=f"workflow-{suffix}",
            name="Workflow tenant",
            initial_admin_user_id=initial_admin_id,
            actor_user_id=actor_id,
        )
        tenant_id = UUID(str(tenant["id"]))

        binding = await store.grant_platform_role(
            actor_user_id=actor_id,
            user_id=target_id,
            role_name="platform_operator",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        bindings, _ = await store.list_platform_role_bindings(limit=10, cursor=None)
        assert any(item["id"] == UUID(str(binding["id"])) for item in bindings)
        assert await store.revoke_platform_role(
            actor_user_id=actor_id, binding_id=UUID(str(binding["id"]))
        )

        requested = await store.request_support_access(
            requester_user_id=target_id,
            tenant_id=tenant_id,
            reason="workflow verification",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        request_id = UUID(str(requested["id"]))
        approved = await store.approve_support_access(
            approver_user_id=approver_id, request_id=request_id
        )
        assert approved is not None
        support = await store.get_support_access(request_id)
        assert support is not None and support["status"] == "approved"
        approver_summary = support["approver"]
        assert isinstance(approver_summary, dict)
        assert approver_summary["id"] == approver_id
        tenant_summary = support["tenant"]
        assert isinstance(tenant_summary, dict)
        assert tenant_summary["id"] == str(tenant_id)
        assert await store.revoke_support_access(actor_user_id=approver_id, request_id=request_id)
        support = await store.get_support_access(request_id)
        assert support is not None and support["status"] == "revoked"
    finally:
        if tenant_id is not None:
            await delete_tenant(engine, tenant_id)
        async with store.session_factory.begin() as session:
            await session.execute(
                delete(SupportAccessRequestModel).where(
                    SupportAccessRequestModel.requester_user_id == target_id
                )
            )
        await _delete_users(store, actor_id, initial_admin_id, target_id, approver_id)


async def test_platform_inventory_and_support_pages_filter_before_limiting(
    engine: AsyncEngine,
) -> None:
    store = SqlAlchemyPlatformStore(real_session_factory(engine))
    tenant_ids = [UUID(int=value) for value in (1001, 1002, 1003)]
    role_ids = [UUID(int=value) for value in (1011, 1012, 1013)]
    requester_id, approver_id = UUID(int=1021), UUID(int=1022)
    request_ids = [UUID(int=value) for value in (1031, 1032, 1033)]
    suffix = uuid4().hex
    now = datetime.now(UTC)
    async with store.session_factory.begin() as session:
        for index, tenant_id in enumerate(tenant_ids):
            session.add(
                TenantModel(
                    id=tenant_id,
                    slug=f"page-{suffix[:12]}-{index}",
                    name=f"Page tenant {index}",
                    status=TenantLifecycleStatus.ACTIVE,
                )
            )
        for index, role_id in enumerate(role_ids):
            session.add(
                PlatformRoleModel(
                    id=role_id,
                    name=f"page-role-{suffix}-{index}",
                    permissions=[],
                    built_in=False,
                )
            )
        for user_id, label in ((requester_id, "Requester"), (approver_id, "Approver")):
            email = f"{user_id}@example.test"
            session.add(
                UserModel(
                    id=user_id,
                    email=email,
                    normalized_email=email,
                    display_name=label,
                    status=UserStatus.ACTIVE,
                )
            )
        await session.flush()
        session.add_all(
            [
                SupportAccessRequestModel(
                    id=request_ids[0],
                    requester_user_id=requester_id,
                    tenant_id=tenant_ids[0],
                    reason="revoked first",
                    expires_at=now + timedelta(minutes=5),
                    revoked_at=now,
                ),
                SupportAccessRequestModel(
                    id=request_ids[1],
                    requester_user_id=requester_id,
                    tenant_id=tenant_ids[1],
                    reason="first pending",
                    expires_at=now + timedelta(minutes=5),
                ),
                SupportAccessRequestModel(
                    id=request_ids[2],
                    requester_user_id=requester_id,
                    tenant_id=tenant_ids[2],
                    reason="second pending",
                    expires_at=now + timedelta(minutes=5),
                ),
            ]
        )
    try:
        tenants, tenant_cursor = await store.list_platform_tenants(limit=2, cursor=None)
        assert [item["id"] for item in tenants] == [str(value) for value in tenant_ids[:2]]
        assert tenant_cursor == tenant_ids[1]
        tenants, tenant_cursor = await store.list_platform_tenants(limit=2, cursor=tenant_cursor)
        assert tenants[0]["id"] == str(tenant_ids[2])

        roles, role_cursor = await store.list_platform_roles(limit=2, cursor=None)
        assert [item["id"] for item in roles] == role_ids[:2]
        assert role_cursor == role_ids[1]
        roles, role_cursor = await store.list_platform_roles(limit=2, cursor=role_cursor)
        assert roles[0]["id"] == role_ids[2]

        pending, next_cursor = await store.list_support_access(
            limit=1, cursor=None, status="pending"
        )
        assert [item["id"] for item in pending] == [request_ids[1]]
        assert next_cursor == request_ids[1]
        pending, next_cursor = await store.list_support_access(
            limit=1, cursor=next_cursor, status="pending"
        )
        assert [item["id"] for item in pending] == [request_ids[2]]
    finally:
        async with store.session_factory.begin() as session:
            await session.execute(
                delete(SupportAccessRequestModel).where(SupportAccessRequestModel.id.in_(request_ids))
            )
            await session.execute(
                delete(PlatformRoleModel).where(PlatformRoleModel.id.in_(role_ids))
            )
            await session.execute(delete(TenantModel).where(TenantModel.id.in_(tenant_ids)))
        await _delete_users(store, requester_id, approver_id)


async def test_expired_platform_role_is_ineffective_and_can_be_regranted(
    engine: AsyncEngine,
) -> None:
    store = SqlAlchemyPlatformStore(real_session_factory(engine))
    actor_id, user_id = uuid4(), uuid4()
    async with store.session_factory.begin() as session:
        for current_id in (actor_id, user_id):
            email = f"{current_id}@example.test"
            session.add(
                UserModel(
                    id=current_id,
                    email=email,
                    normalized_email=email,
                    display_name="Role test",
                )
            )
    try:
        expired_at = datetime.now(UTC) - timedelta(minutes=1)
        await store.grant_platform_role(
            actor_user_id=actor_id,
            user_id=user_id,
            role_name="platform_operator",
            expires_at=expired_at,
        )
        assert await store.effective_permissions(user_id) == frozenset()
        grant = await store.grant_platform_role(
            actor_user_id=actor_id,
            user_id=user_id,
            role_name="platform_operator",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        assert grant["role"] == "platform_operator"
        assert "platform.tenants.read" in await store.effective_permissions(user_id)
    finally:
        await _delete_users(store, actor_id, user_id)


async def test_support_access_expiry_revokes_materialized_tenant_access(
    engine: AsyncEngine,
) -> None:
    store = SqlAlchemyPlatformStore(real_session_factory(engine))
    tenant_id, requester_id, approver_id = uuid4(), uuid4(), uuid4()
    await seed_tenant(engine, tenant_id)
    async with store.session_factory.begin() as session:
        for current_id, label in ((requester_id, "Requester"), (approver_id, "Approver")):
            email = f"{current_id}@example.test"
            session.add(
                UserModel(
                    id=current_id,
                    email=email,
                    normalized_email=email,
                    display_name=label,
                )
            )
    try:
        expires_at = datetime.now(UTC) + timedelta(minutes=1)
        requested = await store.request_support_access(
            requester_user_id=requester_id,
            tenant_id=tenant_id,
            reason="repository expiry test",
            expires_at=expires_at,
        )
        request_id = UUID(str(requested["id"]))
        approved = await store.approve_support_access(
            approver_user_id=approver_id, request_id=request_id
        )
        assert approved is not None
        assert (
            await expire_once(
                store, now=expires_at + timedelta(seconds=1), request_ids=(request_id,)
            )
            == 1
        )
        async with store.session_factory() as session:
            request = await session.get(SupportAccessRequestModel, request_id)
            assert request is not None and request.revoked_at is not None
            membership = await session.get(MembershipModel, request.membership_id)
            binding = await session.get(RoleBindingModel, request.role_binding_id)
            assert membership is not None and membership.status == MembershipStatus.SUSPENDED
            assert membership.authorization_version == 2
            assert binding is not None and binding.revoked_at is not None
    finally:
        await delete_tenant(engine, tenant_id)
        await _delete_users(store, requester_id, approver_id)
