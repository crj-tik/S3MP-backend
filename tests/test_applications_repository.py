"""SqlAlchemyApplicationStore tenant-isolation and CRUD tests against real postgresql."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from _infrastructure import delete_tenant, real_engine, real_session_factory, seed_tenant
from s3mp.applications.infrastructure.models import ApiKeyModel, ApplicationModel, ApplicationOwnerModel
from s3mp.applications.infrastructure.repositories import SqlAlchemyApplicationStore
from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.identity.infrastructure.models import MembershipModel, MembershipStatus, PrincipalModel, PrincipalType, UserModel


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = real_engine()
    yield eng
    await eng.dispose()


async def _seed_principal(session: AsyncSession, tenant_id: UUID) -> str:
    principal = PrincipalModel(
        tenant_id=tenant_id, type=PrincipalType.USER, display_name="Owner",
    )
    session.add(principal)
    await session.flush()
    return str(principal.id)


async def test_list_apps_is_tenant_scoped(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyApplicationStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            principal_id = await _seed_principal(session, tenant_a)
            session.add(ApplicationModel(
                tenant_id=tenant_a, principal_id=UUID(principal_id),
                name="app-alpha", status="active",
            ))
            await session.commit()

        apps_a, _ = await store.list_apps(tenant_a, 50, None)
        apps_b, _ = await store.list_apps(tenant_b, 50, None)
        assert len(apps_a) == 1
        assert apps_a[0]["name"] == "app-alpha"
        assert len(apps_b) == 0
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)


async def test_get_app_returns_none_for_cross_tenant(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyApplicationStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            principal_id = await _seed_principal(session, tenant_a)
            app = ApplicationModel(
                tenant_id=tenant_a, principal_id=UUID(principal_id),
                name="app-beta", status="active",
            )
            session.add(app)
            await session.commit()
            app_id = str(app.id)

        found = await store.get_app(tenant_a, UUID(app_id))
        missing = await store.get_app(tenant_b, UUID(app_id))
        assert found is not None and found["name"] == "app-beta"
        assert missing is None
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)


async def test_create_app_persists_and_round_trips(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyApplicationStore(factory)
    tenant_a = uuid4()
    await seed_tenant(engine, tenant_a)
    try:
        async with factory() as session:
            principal_id = await _seed_principal(session, tenant_a)
            await session.commit()

        created = await store.create_app(tenant_a, "app-gamma", UUID(principal_id))
        assert created["name"] == "app-gamma"
        fetched = await store.get_app(tenant_a, UUID(str(created["id"])))
        assert fetched is not None and fetched["name"] == "app-gamma"
        assert await store.list_owners(tenant_a, UUID(str(created["id"]))) == [
            UUID(principal_id)
        ]
    finally:
        await delete_tenant(engine, tenant_a)


async def test_list_keys_is_tenant_scoped(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyApplicationStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            principal_id = await _seed_principal(session, tenant_a)
            app = ApplicationModel(
                tenant_id=tenant_a, principal_id=UUID(principal_id),
                name="app-keys", status="active",
            )
            session.add(app)
            await session.flush()
            session.add(ApiKeyModel(
                tenant_id=tenant_a, application_id=app.id, key_id="sk_test_1",
                secret_digest=b"x" * 32, pepper_version=1, scopes=["files.read"],
                status="active", expires_at=datetime.now(UTC) + timedelta(days=90),
            ))
            await session.commit()
            app_id = str(app.id)

        keys_a, _ = await store.list_keys(tenant_a, UUID(app_id), 50, None)
        keys_b, _ = await store.list_keys(tenant_b, UUID(app_id), 50, None)
        assert len(keys_a) == 1
        assert keys_a[0]["key_id"] == "sk_test_1"
        assert len(keys_b) == 0
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)


async def test_key_lifecycle_audit_is_redacted_and_atomic(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyApplicationStore(factory)
    tenant_id = uuid4()
    await seed_tenant(engine, tenant_id)
    try:
        async with factory() as session:
            owner_id = UUID(await _seed_principal(session, tenant_id))
            await session.commit()
        application = await store.create_app(tenant_id, "audited", owner_id)
        key = await store.create_key(
            tenant_id,
            UUID(str(application["id"])),
            f"sk_audit_{uuid4().hex}",
            b"secret-digest-must-not-leak",
            1,
            ["files.read"],
            datetime.now(UTC) + timedelta(days=1),
            actor_principal_id=owner_id,
        )
        await store.update_key(
            tenant_id,
            UUID(str(key["id"])),
            "revoked",
            datetime.now(UTC),
            None,
            actor_principal_id=owner_id,
            audit_action="api_key.revoked",
            reason_code="operator_requested",
        )
        async with factory() as session:
            events = list(
                (await session.scalars(
                    select(AuditEventModel).where(
                        AuditEventModel.tenant_id == tenant_id,
                        AuditEventModel.resource_id == str(key["id"]),
                    )
                )).all()
            )
        assert [event.action for event in events] == ["api_key.issued", "api_key.revoked"]
        assert "secret" not in str([event.details for event in events]).lower()
        assert events[1].details["reason_code"] == "operator_requested"
    finally:
        await delete_tenant(engine, tenant_id)


async def test_ownerless_application_is_contained_using_active_memberships(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyApplicationStore(factory)
    tenant_id, owner_id, membership_id, user_id = uuid4(), uuid4(), uuid4(), uuid4()
    await seed_tenant(engine, tenant_id)
    try:
        async with factory.begin() as session:
            session.add(UserModel(id=user_id, email=f"{user_id}@example.test", normalized_email=f"{user_id}@example.test", display_name="Owner"))
            session.add(PrincipalModel(id=owner_id, tenant_id=tenant_id, type=PrincipalType.USER, display_name="Owner"))
            await session.flush()
            session.add(MembershipModel(id=membership_id, tenant_id=tenant_id, user_id=user_id, principal_id=owner_id, status=MembershipStatus.SUSPENDED))
        app = await store.create_app(tenant_id, "orphaned", owner_id)
        app_id = UUID(str(app["id"]))
        assert await store.list_owners(tenant_id, app_id) == [owner_id]
        assert await store.list_active_owners(tenant_id, app_id) == []
        assert await store.recompute_owner_state_for_principal(tenant_id, owner_id) == 1
        contained = await store.get_app(tenant_id, app_id)
        assert contained is not None
        assert (contained["status"], contained["authorization_version"]) == ("pending_takeover", 2)
        assert await store.recompute_owner_state_for_principal(tenant_id, owner_id) == 0
    finally:
        await delete_tenant(engine, tenant_id)


@pytest.mark.parametrize(
    ("status", "expires_at"),
    [
        (MembershipStatus.REMOVED, None),
        (MembershipStatus.ACTIVE, datetime.now(UTC) - timedelta(minutes=1)),
    ],
)
async def test_removed_or_expired_last_owner_is_contained(
    engine: AsyncEngine, status: MembershipStatus, expires_at: datetime | None
) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyApplicationStore(factory)
    tenant_id, owner_id, user_id, membership_id = uuid4(), uuid4(), uuid4(), uuid4()
    await seed_tenant(engine, tenant_id)
    try:
        async with factory.begin() as session:
            email = f"{user_id}@example.test"
            session.add(UserModel(id=user_id, email=email, normalized_email=email, display_name="Owner"))
            session.add(PrincipalModel(
                id=owner_id, tenant_id=tenant_id, type=PrincipalType.USER, display_name="Owner"
            ))
            await session.flush()
            session.add(MembershipModel(
                id=membership_id,
                tenant_id=tenant_id,
                user_id=user_id,
                principal_id=owner_id,
                status=status,
                expires_at=expires_at,
            ))
        app = await store.create_app(tenant_id, "lifecycle", owner_id)
        app_id = UUID(str(app["id"]))
        assert await store.recompute_owner_state_for_principal(tenant_id, owner_id) == 1
        contained = await store.get_app(tenant_id, app_id)
        assert contained is not None and contained["status"] == "pending_takeover"
    finally:
        await delete_tenant(engine, tenant_id)


async def test_pending_application_takeover_restores_owner_and_writes_redacted_audit(
    engine: AsyncEngine,
) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyApplicationStore(factory)
    tenant_id, old_owner_id, new_owner_id = uuid4(), uuid4(), uuid4()
    await seed_tenant(engine, tenant_id)
    try:
        async with factory.begin() as session:
            for principal_id, label in ((old_owner_id, "Former"), (new_owner_id, "New")):
                user_id, membership_id = uuid4(), uuid4()
                session.add(UserModel(id=user_id, email=f"{user_id}@example.test", normalized_email=f"{user_id}@example.test", display_name=label))
                session.add(PrincipalModel(id=principal_id, tenant_id=tenant_id, type=PrincipalType.USER, display_name=label))
                await session.flush()
                session.add(MembershipModel(
                    id=membership_id, tenant_id=tenant_id, user_id=user_id, principal_id=principal_id,
                    status=MembershipStatus.SUSPENDED if principal_id == old_owner_id else MembershipStatus.ACTIVE,
                ))
        app = await store.create_app(tenant_id, "recoverable", old_owner_id)
        app_id = UUID(str(app["id"]))
        assert await store.recompute_owner_state_for_principal(tenant_id, old_owner_id) == 1
        recovered = await store.takeover_app(tenant_id, app_id, new_owner_id, "owner_departed")
        assert recovered is not None
        assert (recovered["status"], recovered["authorization_version"]) == ("active", 3)
        assert new_owner_id in await store.list_active_owners(tenant_id, app_id)
        async with factory() as session:
            events = list((await session.scalars(select(AuditEventModel).where(
                AuditEventModel.tenant_id == tenant_id,
                AuditEventModel.resource_id == str(app_id),
            ))).all())
        takeover = next(event for event in events if event.action == "application.taken_over")
        assert takeover.actor_principal_id == new_owner_id
        assert takeover.details == {"reason_code": "owner_departed"}
        # A repeated event cannot advance authorization state or duplicate audit.
        repeated = await store.takeover_app(tenant_id, app_id, new_owner_id, "duplicate_event")
        assert repeated is not None and repeated["authorization_version"] == 3
    finally:
        await delete_tenant(engine, tenant_id)


async def test_governance_scan_contains_unowned_application_with_audit(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyApplicationStore(factory)
    tenant_id, app_principal_id = uuid4(), uuid4()
    await seed_tenant(engine, tenant_id)
    try:
        async with factory.begin() as session:
            session.add(PrincipalModel(
                id=app_principal_id, tenant_id=tenant_id, type=PrincipalType.APPLICATION, display_name="unowned"
            ))
            await session.flush()
            session.add(ApplicationModel(
                tenant_id=tenant_id, principal_id=app_principal_id, name="unowned", status="active"
            ))
            await session.flush()
            app_id = (await session.scalar(select(ApplicationModel.id).where(
                ApplicationModel.tenant_id == tenant_id, ApplicationModel.principal_id == app_principal_id
            )))
        assert await store.scan_ownerless_applications(tenant_id) == 1
        app = await store.get_app(tenant_id, app_id)
        assert app is not None and app["status"] == "pending_takeover"
        async with factory() as session:
            event = await session.scalar(select(AuditEventModel).where(
                AuditEventModel.tenant_id == tenant_id,
                AuditEventModel.resource_id == str(app_id),
                AuditEventModel.action == "application.ownerless_contained",
            ))
        assert event is not None and event.details == {"reason_code": "no_owner_record"}
    finally:
        await delete_tenant(engine, tenant_id)
