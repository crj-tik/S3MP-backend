"""SqlAlchemyStorageStore tenant-isolation and CRUD tests against real postgresql."""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from _infrastructure import delete_tenant, real_engine, real_session_factory, seed_tenant
from s3mp.storage.infrastructure.models import StorageConnectionModel, StorageSpaceModel
from s3mp.storage.infrastructure.repositories import SqlAlchemyStorageStore


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = real_engine()
    yield eng
    await eng.dispose()


async def _seed_connection(session: AsyncSession, tenant_id: UUID) -> str:
    conn = StorageConnectionModel(
        tenant_id=tenant_id,
        name="primary",
        endpoint="https://s3.example.com",
        region="us-east-1",
        path_style=True,
        credential_reference="vault/s3",
    )
    session.add(conn)
    await session.flush()
    return str(conn.id)


async def _seed_space(session: AsyncSession, tenant_id: UUID, conn_id: str) -> str:
    from uuid import UUID

    space = StorageSpaceModel(
        tenant_id=tenant_id,
        connection_id=UUID(conn_id),
        name="default",
        bucket="s3mp-dev",
        root_prefix="",
    )
    session.add(space)
    await session.flush()
    return str(space.id)


async def test_list_connections_is_tenant_scoped(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyStorageStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            await _seed_connection(session, tenant_a)
            await session.commit()

        conns_a, _ = await store.list_connections(tenant_a)
        conns_b, _ = await store.list_connections(tenant_b)
        assert len(conns_a) == 1
        assert conns_a[0]["name"] == "primary"
        assert len(conns_b) == 0
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)


async def test_get_connection_returns_none_for_cross_tenant(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyStorageStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            conn_id = await _seed_connection(session, tenant_a)
            await session.commit()

        found = await store.get_connection(tenant_a, UUID(conn_id))
        missing = await store.get_connection(tenant_b, UUID(conn_id))
        assert found is not None and found["name"] == "primary"
        assert missing is None
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)


async def test_list_spaces_is_tenant_scoped(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyStorageStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            conn_id = await _seed_connection(session, tenant_a)
            await _seed_space(session, tenant_a, conn_id)
            await session.commit()

        spaces_a, _ = await store.list_spaces(tenant_a)
        spaces_b, _ = await store.list_spaces(tenant_b)
        # Legacy spaces without an application namespace are quarantined and
        # must not be exposed as readable storage targets.
        assert len(spaces_a) == 0
        assert len(spaces_b) == 0
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)


async def test_ensure_managed_connection_is_idempotent_and_tenant_scoped(
    engine: AsyncEngine,
) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyStorageStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    profile: dict[str, object] = {
        "endpoint": "http://s3.internal:9000",
        "region": "us-east-1",
        "bucket": "shared-bucket",
        "path_style": True,
        "credential_reference": "settings:s3",
        "profile_version": 3,
    }
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        first = await store.ensure_managed_connection(tenant_a, profile)
        second = await store.ensure_managed_connection(tenant_a, profile)
        other = await store.ensure_managed_connection(tenant_b, profile)

        assert first["id"] == second["id"]
        assert first["id"] != other["id"]
        assert first["name"] == "__s3mp_managed_shared_profile_v3__"
        assert first["endpoint"] == "http://s3.internal:9000"
        assert first["path_style"] is True
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)
