"""SqlAlchemyQuotaStore and SqlAlchemyAuditStore tenant-isolation tests against real pg."""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from _infrastructure import delete_tenant, real_engine, real_session_factory, seed_tenant
from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.governance.infrastructure.models import QuotaModel
from s3mp.governance.infrastructure.repositories import SqlAlchemyAuditStore, SqlAlchemyQuotaStore


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = real_engine()
    yield eng
    await eng.dispose()


async def test_list_quotas_is_tenant_scoped(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyQuotaStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            session.add(
                QuotaModel(
                    tenant_id=tenant_a,
                    limit_bytes=1073741824,
                    used_bytes=0,
                    reserved_bytes=0,
                )
            )
            await session.commit()

        quotas_a, _ = await store.list_quotas(tenant_a, None)
        quotas_b, _ = await store.list_quotas(tenant_b, None)
        assert len(quotas_a) == 1
        assert quotas_a[0]["limit_bytes"] == 1073741824
        assert len(quotas_b) == 0
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)


async def test_get_quota_returns_none_for_cross_tenant(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyQuotaStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            quota = QuotaModel(
                tenant_id=tenant_a,
                limit_bytes=1073741824,
                used_bytes=0,
                reserved_bytes=0,
            )
            session.add(quota)
            await session.commit()
            quota_id = str(quota.id)

        found = await store.get_quota(tenant_a, UUID(quota_id))
        missing = await store.get_quota(tenant_b, UUID(quota_id))
        assert found is not None and found["limit_bytes"] == 1073741824
        assert missing is None
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)


async def test_list_audit_events_is_tenant_scoped(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyAuditStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            session.add(
                AuditEventModel(
                    tenant_id=tenant_a,
                    action="file.upload",
                    resource_type="file_object",
                    details={"object_key": "a.txt"},
                )
            )
            await session.commit()

        events_a, _ = await store.list_events(tenant_a, {})
        events_b, _ = await store.list_events(tenant_b, {})
        assert len(events_a) == 1
        assert events_a[0]["action"] == "file.upload"
        assert len(events_b) == 0
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)


async def test_get_audit_event_returns_none_for_cross_tenant(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyAuditStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            event = AuditEventModel(
                tenant_id=tenant_a,
                action="file.delete",
                resource_type="file_object",
                details={},
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)

        found = await store.get_event(tenant_a, UUID(event_id))
        missing = await store.get_event(tenant_b, UUID(event_id))
        assert found is not None and found["action"] == "file.delete"
        assert missing is None
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)
