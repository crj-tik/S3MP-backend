"""Files upload end-to-end with real postgresql and the real file service.

Verifies the full HTTP → FileApplicationService → SqlAlchemyFileStore → real pg
chain: create an upload via HTTP, read it back, confirm cross-tenant isolation.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from _infrastructure import (
    delete_tenant,
    real_engine,
    real_session_factory,
    real_settings,
    seed_tenant,
)
from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.authorization.infrastructure.models import (
    BindingEffect,
    GroupMemberModel,
    GroupModel,
    PermissionModel,
    RoleBindingModel,
    RoleModel,
    RolePermissionModel,
)
from s3mp.files.infrastructure.authorization_repository import SqlAlchemyFileAuthorizationStore
from s3mp.files.infrastructure.ingestion_models import FileIngestionRecordModel
from s3mp.files.infrastructure.models import UploadSessionModel
from s3mp.governance.infrastructure.models import QuotaModel, QuotaReservationModel
from s3mp.identity.domain.context import PrincipalContext
from s3mp.identity.infrastructure.models import PrincipalModel, PrincipalType
from s3mp.main import create_app
from s3mp.storage.infrastructure.models import StorageConnectionModel, StorageSpaceModel


async def _seed_space(session: Any, tenant_id: Any) -> str:
    connection = StorageConnectionModel(
        tenant_id=tenant_id, name="group-test", endpoint="https://s3.example.com",
        region="us-east-1", path_style=True, credential_reference="vault/s3",
    )
    session.add(connection)
    await session.flush()
    space = StorageSpaceModel(
        tenant_id=tenant_id, connection_id=connection.id, name="group-test",
        bucket="s3mp-dev", root_prefix="",
    )
    session.add(space)
    await session.flush()
    return str(space.id)


async def test_upload_create_and_get_round_trips_through_real_pg() -> None:
    app = create_app(real_settings())
    async with app.router.lifespan_context(app):
        engine = app.state.engine
        factory = real_session_factory(engine)
        tenant_id = uuid4()
        await seed_tenant(engine, tenant_id)
        try:
            principal_id = uuid4()
            async with factory() as session:
                conn = StorageConnectionModel(
                    tenant_id=tenant_id, name="primary", endpoint="https://s3.example.com",
                    region="us-east-1", path_style=True, credential_reference="vault/s3",
                )
                session.add(conn)
                await session.flush()
                space = StorageSpaceModel(
                    tenant_id=tenant_id, connection_id=conn.id, name="default",
                    bucket="s3mp-dev", root_prefix="",
                )
                session.add(space)
                await session.flush()
                session.add(PrincipalModel(
                    id=principal_id, tenant_id=tenant_id, type=PrincipalType.USER,
                    display_name="E2E",
                ))
                permission = await session.scalar(
                    select(PermissionModel).where(PermissionModel.name == "files.write")
                )
                if permission is None:
                    permission = PermissionModel(
                        name="files.write",
                        resource_type="storage_object",
                        delegable=True,
                        description="E2E upload permission",
                    )
                    session.add(permission)
                role = RoleModel(tenant_id=tenant_id, name="uploader")
                session.add(role)
                await session.flush()
                session.add(RolePermissionModel(role_id=role.id, permission_id=permission.id))
                session.add(RoleBindingModel(
                    tenant_id=tenant_id,
                    principal_id=principal_id,
                    role_id=role.id,
                    effect=BindingEffect.ALLOW,
                    storage_space_id=space.id,
                    canonical_prefix=None,
                    reason="E2E fixture",
                    starts_at=datetime.now(UTC) - timedelta(minutes=1),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                    created_by_principal_id=principal_id,
                ))
                await session.commit()
                space_id = str(space.id)

            ctx = PrincipalContext(tenant_id, principal_id, uuid4(), 1)

            @app.middleware("http")
            async def inject(request: Any, call_next: Any) -> Any:
                request.state.principal_context = ctx
                return await call_next(request)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                create = await client.post(
                    f"/api/v1/storage_spaces/{space_id}/uploads",
                    json={
                        "object_key": "e2e/test.txt",
                        "content_length": 42,
                        "content_type": "text/plain",
                    },
                    headers={"Idempotency-Key": "e2e-upload-create-1"},
                )
                replay = await client.post(
                    f"/api/v1/storage_spaces/{space_id}/uploads",
                    json={
                        "object_key": "e2e/test.txt",
                        "content_length": 42,
                        "content_type": "text/plain",
                    },
                    headers={"Idempotency-Key": "e2e-upload-create-1"},
                )
                upload_id = create.json()["id"]
                fetched = await client.get(f"/api/v1/uploads/{upload_id}")

            assert create.status_code == 201
            assert replay.status_code == 201
            assert replay.json()["id"] == upload_id
            assert replay.json()["ingestion_id"] == create.json()["ingestion_id"]
            assert create.json()["object_key"] == "e2e/test.txt"
            assert create.json()["status"] == "pending"
            assert fetched.status_code == 200
            assert fetched.json()["object_key"] == "e2e/test.txt"
            async with factory() as session:
                upload_count = await session.scalar(
                    select(func.count()).select_from(UploadSessionModel).where(
                        UploadSessionModel.tenant_id == tenant_id
                    )
                )
                ingestion_count = await session.scalar(
                    select(func.count()).select_from(FileIngestionRecordModel).where(
                        FileIngestionRecordModel.tenant_id == tenant_id
                    )
                )
            assert upload_count == 1
            assert ingestion_count == 1
            async with factory() as session:
                persisted_request_id = await session.scalar(
                    select(FileIngestionRecordModel.request_id).where(
                        FileIngestionRecordModel.tenant_id == tenant_id
                    )
                )
            assert persisted_request_id
        finally:
            await delete_tenant(engine, tenant_id)


async def test_human_group_binding_is_loaded_but_application_is_direct_only() -> None:
    database_engine = real_engine()
    factory = real_session_factory(database_engine)
    tenant_id, human_id, application_id, group_principal_id = (uuid4() for _ in range(4))
    await seed_tenant(database_engine, tenant_id)
    try:
        async with factory() as session:
            space_id = await _seed_space(session, tenant_id)
            session.add_all([
                PrincipalModel(id=human_id, tenant_id=tenant_id, type=PrincipalType.USER, display_name="Human"),
                PrincipalModel(id=application_id, tenant_id=tenant_id, type=PrincipalType.APPLICATION, display_name="App"),
                PrincipalModel(id=group_principal_id, tenant_id=tenant_id, type=PrincipalType.GROUP, display_name="Group"),
            ])
            await session.flush()
            group = GroupModel(tenant_id=tenant_id, principal_id=group_principal_id, name="writers")
            session.add(group)
            await session.flush()
            session.add(GroupMemberModel(tenant_id=tenant_id, group_id=group.id, principal_id=human_id))
            permission = await session.scalar(select(PermissionModel).where(PermissionModel.name == "files.write"))
            assert permission is not None
            role = RoleModel(tenant_id=tenant_id, name="group-writer")
            session.add(role)
            await session.flush()
            session.add(RolePermissionModel(role_id=role.id, permission_id=permission.id))
            session.add(RoleBindingModel(
                tenant_id=tenant_id, principal_id=group_principal_id, role_id=role.id,
                effect=BindingEffect.ALLOW, storage_space_id=UUID(space_id), canonical_prefix=None,
                reason="group fixture", starts_at=datetime.now(UTC) - timedelta(minutes=1),
                expires_at=datetime.now(UTC) + timedelta(hours=1), created_by_principal_id=human_id,
            ))
            await session.commit()
        store = SqlAlchemyFileAuthorizationStore(factory)
        human_bindings = await store.bindings_for(tenant_id, human_id, UUID(space_id), subject_kind="human")
        application_bindings = await store.bindings_for(tenant_id, application_id, UUID(space_id), subject_kind="application")
        assert [binding.permission for binding in human_bindings] == ["files.write"]
        assert application_bindings == []
    finally:
        await delete_tenant(database_engine, tenant_id)
        await database_engine.dispose()


async def test_ingestion_commit_writes_redacted_audit_evidence() -> None:
    app = create_app(real_settings())
    async with app.router.lifespan_context(app):
        engine = app.state.engine
        factory = real_session_factory(engine)
        tenant_id, principal_id = uuid4(), uuid4()
        await seed_tenant(engine, tenant_id)
        try:
            async with factory.begin() as session:
                space_id = UUID(await _seed_space(session, tenant_id))
                session.add(PrincipalModel(
                    id=principal_id, tenant_id=tenant_id, type=PrincipalType.USER, display_name="Audit",
                ))
                await session.flush()
            from s3mp.files.infrastructure.ingestion_repository import SqlAlchemyIngestionStore

            store = SqlAlchemyIngestionStore(factory)
            created = await store.create_upload_intent(
                tenant_id,
                {
                    "principal_id": str(principal_id), "storage_space_id": str(space_id),
                    "object_key": "tenant/secret/report.csv", "content_length": 3,
                    "content_type": "text/csv", "expires_at": datetime.now(UTC) + timedelta(hours=1),
                },
                {
                    "creator_principal_id": str(principal_id), "acting_principal_id": str(principal_id),
                    "storage_space_id": str(space_id), "bucket": "s3mp-dev", "relative_key": "report.csv",
                    "physical_key": "tenant/secret/report.csv", "authorization_evidence": {"decision": "allow"},
                    "authorization_version": 1, "request_id": "audit-request", "idempotency_key": "audit-intent-1",
                    "idempotency_fingerprint": "a" * 64,
                },
            )
            ingestion_id = UUID(created["ingestion_id"])
            await store.record_provider_result(
                tenant_id, ingestion_id, provider_etag="etag", actual_size=3,
                actual_content_type="text/csv",
            )
            committed = await store.commit_verified_file(tenant_id, ingestion_id)
            async with factory() as session:
                audit = await session.scalar(
                    select(AuditEventModel).where(
                        AuditEventModel.tenant_id == tenant_id,
                        AuditEventModel.resource_id == committed["file_object"]["id"],
                    )
                )
            assert audit is not None
            assert audit.details["request_id"] == "audit-request"
            assert "object_key_fingerprint" in audit.details
            assert "tenant/secret/report.csv" not in str(audit.details)
        finally:
            await delete_tenant(engine, tenant_id)


async def test_ingestion_reserves_and_settles_configured_space_quota() -> None:
    database_engine = real_engine()
    factory = real_session_factory(database_engine)
    tenant_id, principal_id = uuid4(), uuid4()
    await seed_tenant(database_engine, tenant_id)
    try:
        async with factory.begin() as session:
            space_id = UUID(await _seed_space(session, tenant_id))
            session.add(PrincipalModel(
                id=principal_id, tenant_id=tenant_id, type=PrincipalType.USER, display_name="Quota",
            ))
            session.add(QuotaModel(
                tenant_id=tenant_id, storage_space_id=space_id, limit_bytes=10,
                used_bytes=0, reserved_bytes=0,
            ))
        from s3mp.files.infrastructure.ingestion_repository import SqlAlchemyIngestionStore

        store = SqlAlchemyIngestionStore(factory)
        created = await store.create_upload_intent(
            tenant_id,
            {
                "principal_id": str(principal_id), "storage_space_id": str(space_id),
                "object_key": "quota/a.txt", "content_length": 3, "content_type": "text/plain",
                "expires_at": datetime.now(UTC) + timedelta(hours=1),
            },
            {
                "creator_principal_id": str(principal_id), "acting_principal_id": str(principal_id),
                "storage_space_id": str(space_id), "bucket": "s3mp-dev", "relative_key": "a.txt",
                "physical_key": "quota/a.txt", "authorization_evidence": {"decision": "allow"},
                "authorization_version": 1, "request_id": "quota-request", "idempotency_key": "quota-intent-1",
                "idempotency_fingerprint": "b" * 64,
            },
        )
        async with factory() as session:
            quota = await session.scalar(select(QuotaModel).where(QuotaModel.tenant_id == tenant_id))
            reservation = await session.scalar(
                select(QuotaReservationModel).where(QuotaReservationModel.tenant_id == tenant_id)
            )
        assert quota is not None and quota.reserved_bytes == 3
        assert reservation is not None and reservation.status == "reserved"
        ingestion_id = UUID(created["ingestion_id"])
        await store.record_provider_result(
            tenant_id, ingestion_id, provider_etag="quota-etag", actual_size=3,
            actual_content_type="text/plain",
        )
        await store.commit_verified_file(tenant_id, ingestion_id)
        async with factory() as session:
            quota = await session.scalar(select(QuotaModel).where(QuotaModel.tenant_id == tenant_id))
            reservation = await session.scalar(
                select(QuotaReservationModel).where(QuotaReservationModel.tenant_id == tenant_id)
            )
        assert quota is not None and (quota.used_bytes, quota.reserved_bytes) == (3, 0)
        assert reservation is not None and (reservation.status, reservation.actual_bytes) == ("settled", 3)
    finally:
        await delete_tenant(database_engine, tenant_id)
        await database_engine.dispose()


async def test_ingestion_rejects_conflicting_idempotency_reuse() -> None:
    database_engine = real_engine()
    factory = real_session_factory(database_engine)
    tenant_id, principal_id = uuid4(), uuid4()
    await seed_tenant(database_engine, tenant_id)
    try:
        async with factory.begin() as session:
            space_id = UUID(await _seed_space(session, tenant_id))
            session.add(PrincipalModel(
                id=principal_id, tenant_id=tenant_id, type=PrincipalType.USER, display_name="Idempotency",
            ))
        from s3mp.files.infrastructure.ingestion_repository import SqlAlchemyIngestionStore

        store = SqlAlchemyIngestionStore(factory)
        base = {
            "creator_principal_id": str(principal_id), "acting_principal_id": str(principal_id),
            "storage_space_id": str(space_id), "bucket": "s3mp-dev", "relative_key": "one.txt",
            "physical_key": "idem/one.txt", "authorization_evidence": {"decision": "allow"},
            "authorization_version": 1, "request_id": "idem-request", "idempotency_key": "same-key-1",
        }
        session_data = {
            "principal_id": str(principal_id), "storage_space_id": str(space_id),
            "object_key": "idem/one.txt", "content_length": 1, "content_type": "text/plain",
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
        }
        await store.create_upload_intent(tenant_id, session_data, {**base, "idempotency_fingerprint": "c" * 64})
        with pytest.raises(Exception) as exc_info:
            await store.create_upload_intent(
                tenant_id, session_data, {**base, "physical_key": "idem/two.txt", "idempotency_fingerprint": "d" * 64}
            )
        assert getattr(exc_info.value, "code", None) == "idempotency_key_reused"
    finally:
        await delete_tenant(database_engine, tenant_id)
        await database_engine.dispose()
