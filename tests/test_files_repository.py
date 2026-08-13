"""SqlAlchemyFileStore tenant-isolation tests against real postgresql."""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from _infrastructure import delete_tenant, real_engine, real_session_factory, seed_tenant
from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.common.errors import ApiError
from s3mp.files.infrastructure.models import FileObjectModel, FileOperationModel
from s3mp.files.infrastructure.repositories import SqlAlchemyFileStore
from s3mp.identity.infrastructure.models import PrincipalModel, PrincipalType
from s3mp.storage.infrastructure.models import StorageConnectionModel, StorageSpaceModel


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = real_engine()
    yield eng
    await eng.dispose()


async def _seed_space(session: AsyncSession, tenant_id: UUID) -> tuple[UUID, UUID]:
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
    space = StorageSpaceModel(
        tenant_id=tenant_id,
        connection_id=conn.id,
        name="default",
        bucket="s3mp-dev",
        root_prefix="",
    )
    session.add(space)
    await session.flush()
    return space.id, conn.id


async def test_list_files_is_tenant_scoped(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyFileStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            space_id, _ = await _seed_space(session, tenant_a)
            session.add(
                FileObjectModel(
                    tenant_id=tenant_a,
                    storage_space_id=space_id,
                    object_key="docs/a.txt",
                    content_length=100,
                    content_type="text/plain",
                )
            )
            await session.commit()

        files_a = await store.list_files(tenant_a, space_id, "")
        files_b = await store.list_files(tenant_b, space_id, "")
        assert len(files_a) == 1
        assert files_a[0]["object_key"] == "docs/a.txt"
        assert len(files_b) == 0
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)


async def test_list_files_respects_directory_boundary(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyFileStore(factory)
    tenant_id = uuid4()
    await seed_tenant(engine, tenant_id)
    try:
        async with factory() as session:
            space_id, _ = await _seed_space(session, tenant_id)
            session.add_all(
                [
                    FileObjectModel(
                        tenant_id=tenant_id,
                        storage_space_id=space_id,
                        object_key="team/a.txt",
                        content_length=1,
                        content_type="text/plain",
                    ),
                    FileObjectModel(
                        tenant_id=tenant_id,
                        storage_space_id=space_id,
                        object_key="team2/secret.txt",
                        content_length=1,
                        content_type="text/plain",
                    ),
                ]
            )
            await session.commit()
        files = await store.list_files(tenant_id, space_id, "team")
        assert [file["object_key"] for file in files] == ["team/a.txt"]
    finally:
        await delete_tenant(engine, tenant_id)


async def test_get_file_returns_none_for_cross_tenant(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyFileStore(factory)
    tenant_a, tenant_b = uuid4(), uuid4()
    await seed_tenant(engine, tenant_a)
    await seed_tenant(engine, tenant_b)
    try:
        async with factory() as session:
            space_id, _ = await _seed_space(session, tenant_a)
            file_obj = FileObjectModel(
                tenant_id=tenant_a,
                storage_space_id=space_id,
                object_key="docs/b.txt",
                content_length=50,
                content_type="text/plain",
            )
            session.add(file_obj)
            await session.commit()
            file_id = file_obj.id

        found = await store.get_file(tenant_a, space_id, file_id)
        missing = await store.get_file(tenant_b, space_id, file_id)
        assert found is not None and found["object_key"] == "docs/b.txt"
        assert missing is None
    finally:
        await delete_tenant(engine, tenant_a)
        await delete_tenant(engine, tenant_b)


async def test_create_upload_and_get_upload_round_trip(engine: AsyncEngine) -> None:

    factory = real_session_factory(engine)
    store = SqlAlchemyFileStore(factory)
    tenant_a = uuid4()
    await seed_tenant(engine, tenant_a)
    try:
        async with factory() as session:
            space_id, _ = await _seed_space(session, tenant_a)
            principal = PrincipalModel(
                tenant_id=tenant_a,
                type=PrincipalType.USER,
                display_name="Uploader",
            )
            session.add(principal)
            await session.commit()
            principal_id = str(principal.id)

        upload = await store.create_upload(
            tenant_a,
            space_id,
            {
                "principal_id": principal_id,
                "object_key": "docs/upload.txt",
                "content_length": 200,
                "content_type": "text/plain",
                "checksum": None,
            },
        )
        fetched = await store.get_upload(tenant_a, upload["id"])
        assert fetched is not None
        assert fetched["object_key"] == "docs/upload.txt"
        # Cross-tenant: a random tenant cannot see tenant A's upload
        missing = await store.get_upload(uuid4(), upload["id"])
        assert missing is None
    finally:
        await delete_tenant(engine, tenant_a)


async def test_delete_queues_recoverable_intent_only_after_etag_match(engine: AsyncEngine) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyFileStore(factory)
    tenant_id, principal_id = uuid4(), uuid4()
    await seed_tenant(engine, tenant_id)
    try:
        async with factory() as session:
            space_id, _ = await _seed_space(session, tenant_id)
            session.add(
                PrincipalModel(
                    id=principal_id,
                    tenant_id=tenant_id,
                    type=PrincipalType.USER,
                    display_name="Delete",
                )
            )
            file_obj = FileObjectModel(
                tenant_id=tenant_id,
                storage_space_id=space_id,
                object_key="private/deleteme.txt",
                content_length=1,
                content_type="text/plain",
                etag="current",
            )
            session.add(file_obj)
            await session.commit()
        with pytest.raises(ApiError) as exc_info:
            await store.delete_file(
                tenant_id,
                space_id,
                file_obj.id,
                if_match="stale",
                actor_principal_id=principal_id,
            )
        assert exc_info.value.code == "etag_mismatch"
        found = await store.get_file(tenant_id, space_id, file_obj.id)
        assert found is not None and found["status"] == "available"
        await store.delete_file(
            tenant_id,
            space_id,
            file_obj.id,
            if_match="current",
            actor_principal_id=principal_id,
            request_id="delete-request",
            object_key="private/deleteme.txt",
        )
        assert await store.get_file(tenant_id, space_id, file_obj.id) is None
        pending = await store.list_pending_deletions()
        assert [row["id"] for row in pending if row["tenant_id"] == str(tenant_id)] == [
            str(file_obj.id)
        ]
        async with factory() as session:
            audit = await session.scalar(
                select(AuditEventModel).where(AuditEventModel.resource_id == str(file_obj.id))
            )
        assert audit is not None and "private/deleteme.txt" not in str(audit.details)
        await store.finalize_file_delete(tenant_id, file_obj.id)
        assert not [
            row for row in await store.list_pending_deletions() if row["id"] == str(file_obj.id)
        ]
    finally:
        await delete_tenant(engine, tenant_id)


async def test_concurrent_workers_claim_operation_once_and_retry_exhausts(
    engine: AsyncEngine,
) -> None:
    factory = real_session_factory(engine)
    store = SqlAlchemyFileStore(factory)
    tenant_id, principal_id = uuid4(), uuid4()
    await seed_tenant(engine, tenant_id)
    try:
        async with factory() as session:
            space_id, _ = await _seed_space(session, tenant_id)
            session.add(
                PrincipalModel(
                    id=principal_id,
                    tenant_id=tenant_id,
                    type=PrincipalType.USER,
                    display_name="Worker",
                )
            )
            await session.flush()
            operation = FileOperationModel(
                tenant_id=tenant_id,
                principal_id=principal_id,
                storage_space_id=space_id,
                operation_type="copy",
                source_key="source",
                destination_key="destination",
                keys=[],
                status="pending",
                idempotency_key="worker-claim",
                authorization_evidence={"subject_kind": "human"},
            )
            session.add(operation)
            await session.commit()
            operation_id = operation.id
        first, second = await asyncio.gather(
            store.claim_operations("worker-a", 1), store.claim_operations("worker-b", 1)
        )
        assert len(first) + len(second) == 1
        async with factory.begin() as session:
            row = await session.get(FileOperationModel, operation_id)
            assert row is not None
            row.status = "running"
            row.next_retry_at = None
            row.attempt_count = 5
        await store.finish_operation(tenant_id, operation_id, "retry_wait", "provider")
        final = await store.get_operation(tenant_id, operation_id)
        assert final is not None
        assert final["status"] == "failed"
        assert final["failure_reason"] == "retry_exhausted"
    finally:
        await delete_tenant(engine, tenant_id)
