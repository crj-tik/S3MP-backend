"""SQLAlchemy repository for file objects, uploads, multipart sessions, and operations."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.common.errors import ApiError
from s3mp.common.logging import instrument_async_methods
from s3mp.files.domain.file_reference import generate_file_ref
from s3mp.files.domain.file_status import FileObjectStatus
from s3mp.files.infrastructure.models import (
    FileDeletionRecordModel,
    FileObjectModel,
    FileOperationEventOutboxModel,
    FileOperationModel,
    FileOperationResourceReservationModel,
    FileRetentionOutboxModel,
    MultipartPartModel,
    MultipartSessionModel,
    UploadSessionModel,
)
from s3mp.governance.infrastructure.models import QuotaAdjustmentModel, QuotaModel
from s3mp.storage.infrastructure.models import StorageSpaceModel
from s3mp.tenant.infrastructure.models import TenantModel


@instrument_async_methods("repository")
class SqlAlchemyFileStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Files ──────────────────────────────────────────────────────────────

    async def list_files(
        self,
        tenant_id: UUID,
        space_id: UUID,
        prefix: str,
        status: FileObjectStatus = FileObjectStatus.AVAILABLE,
    ) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = (
                select(FileObjectModel)
                .join(
                    StorageSpaceModel,
                    (StorageSpaceModel.tenant_id == FileObjectModel.tenant_id)
                    & (StorageSpaceModel.id == FileObjectModel.storage_space_id),
                )
                .join(TenantModel, TenantModel.id == FileObjectModel.tenant_id)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.status == status.value,
                    FileObjectModel.soft_deleted.is_(False),
                    StorageSpaceModel.status == "active",
                    TenantModel.status == "active",
                )
            )
            if prefix:
                # A directory prefix is a segment boundary, not a lexical
                # prefix: `team` must not enumerate `team2`.
                stmt = stmt.where(
                    or_(
                        FileObjectModel.object_key == prefix,
                        FileObjectModel.object_key.startswith(prefix + "/", autoescape=True),
                    )
                )
            rows = (await session.scalars(stmt.order_by(FileObjectModel.object_key))).all()
            return [_file_dict(r) for r in rows]

    async def get_file(
        self, tenant_id: UUID, space_id: UUID, file_id: UUID
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(FileObjectModel)
                .join(
                    StorageSpaceModel,
                    (StorageSpaceModel.tenant_id == FileObjectModel.tenant_id)
                    & (StorageSpaceModel.id == FileObjectModel.storage_space_id),
                )
                .join(TenantModel, TenantModel.id == FileObjectModel.tenant_id)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.id == file_id,
                    FileObjectModel.status == "available",
                    FileObjectModel.soft_deleted.is_(False),
                    StorageSpaceModel.status == "active",
                    TenantModel.status == "active",
                )
            )
            return _file_dict(row) if row else None

    async def get_file_by_ref(
        self, tenant_id: UUID, space_id: UUID, public_file_ref: str
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(FileObjectModel)
                .join(
                    StorageSpaceModel,
                    (StorageSpaceModel.tenant_id == FileObjectModel.tenant_id)
                    & (StorageSpaceModel.id == FileObjectModel.storage_space_id),
                )
                .join(TenantModel, TenantModel.id == FileObjectModel.tenant_id)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.public_file_ref == public_file_ref,
                    FileObjectModel.status == "available",
                    FileObjectModel.soft_deleted.is_(False),
                    StorageSpaceModel.status == "active",
                    TenantModel.status == "active",
                )
            )
            return _file_dict(row) if row else None

    async def file_name_is_occupied(
        self, tenant_id: UUID, space_id: UUID, physical_key: str
    ) -> bool:
        """Mirror the active-key index so preflight cannot claim a busy name is free."""
        async with self._sf() as session:
            row = await session.scalar(
                select(FileObjectModel.id)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.object_key == physical_key,
                    or_(
                        FileObjectModel.soft_deleted.is_(True),
                        FileObjectModel.status.in_(
                            (
                                "available",
                                "renaming",
                                "rename_failed",
                                "deleting",
                                "delete_failed",
                            )
                        ),
                    ),
                )
                .limit(1)
            )
            if row is not None:
                return True
            reservation = await session.scalar(
                select(FileOperationResourceReservationModel.id)
                .where(
                    FileOperationResourceReservationModel.tenant_id == tenant_id,
                    FileOperationResourceReservationModel.storage_space_id == space_id,
                    FileOperationResourceReservationModel.object_key == physical_key,
                )
                .limit(1)
            )
            return reservation is not None

    async def file_name_is_migrating(
        self, tenant_id: UUID, space_id: UUID, physical_key: str
    ) -> bool:
        async with self._sf() as session:
            row = await session.scalar(
                select(FileDeletionRecordModel.id).where(
                    FileDeletionRecordModel.tenant_id == tenant_id,
                    FileDeletionRecordModel.storage_space_id == space_id,
                    FileDeletionRecordModel.original_physical_key == physical_key,
                    FileDeletionRecordModel.status.in_(("requested", "moving", "retrying")),
                )
            )
            return row is not None

    async def update_file_metadata(
        self, tenant_id: UUID, space_id: UUID, file_id: UUID, **data: Any
    ) -> dict[str, Any] | None:
        """Replace opaque application metadata without touching the stored object."""
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.id == file_id,
                    FileObjectModel.status == "available",
                    FileObjectModel.soft_deleted.is_(False),
                )
                .with_for_update()
            )
            if row is None:
                return None
            if row.active_operation_id is not None:
                raise ApiError(
                    "file_operation_in_progress",
                    "File is occupied by an asynchronous operation",
                    status_code=409,
                )
            fingerprint = str(data["request_fingerprint"])
            if row.metadata_update_idempotency_key == data["idempotency_key"]:
                if row.metadata_update_fingerprint != fingerprint:
                    raise ApiError(
                        "idempotency_key_reused",
                        "Idempotency key was used for a different metadata update",
                        status_code=409,
                    )
                return _file_dict(row)
            if _record_etag(row) != data["if_match"]:
                from s3mp.common.api.etag import check_etag

                check_etag(_record_etag(row), str(data["if_match"]))
            row.metadata_json = data["metadata"]
            row.public_file_ref = data.get("public_file_ref")
            row.record_version += 1
            row.metadata_update_idempotency_key = str(data["idempotency_key"])
            row.metadata_update_fingerprint = fingerprint
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=data.get("actor_principal_id"),
                    action="file.metadata_updated",
                    resource_type="file_object",
                    resource_id=str(row.id),
                    details={
                        "request_id": data.get("request_id"),
                        "storage_space_id": str(space_id),
                    },
                )
            )
            await session.flush()
            return _file_dict(row)

    async def delete_file(
        self, tenant_id: UUID, space_id: UUID, file_id: UUID, **data: Any
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel).where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.id == file_id,
                )
            )
            if row is not None:
                if row.soft_deleted and row.deletion_idempotency_key == data.get("idempotency_key"):
                    return _file_dict(row)
                if row.status != "available" or row.soft_deleted:
                    return None
                if row.active_operation_id is not None:
                    raise ApiError(
                        "file_operation_in_progress",
                        "File is occupied by an asynchronous operation",
                        status_code=409,
                    )
                _validate_delete_etag(
                    row.etag,
                    data.get("if_match"),
                    is_file_ref=data.get("reference_kind") == "file_ref"
                    or bool(data.get("allow_missing_if_match")),
                )
                session.add(
                    AuditEventModel(
                        tenant_id=tenant_id,
                        actor_principal_id=data.get("actor_principal_id"),
                        action="file.deleted",
                        resource_type="file_object",
                        resource_id=str(row.id),
                        details={
                            "request_id": data.get("request_id"),
                            "storage_space_id": str(space_id),
                            "object_key_fingerprint": hashlib.sha256(
                                str(data.get("object_key", row.object_key)).encode("utf-8")
                            ).hexdigest(),
                        },
                    )
                )
                due_at = data["purge_due_at"]
                deleted_at = datetime.now(UTC)
                deletion_id = uuid4()
                original_key = str(row.object_key)
                original_relative_key = str(data.get("original_relative_key") or original_key)
                basename = original_key.rsplit("/", 1)[-1]
                parent = original_key.rsplit("/", 1)[0] if "/" in original_key else ""
                stamp = deleted_at.strftime("%Y%m%dT%H%M%S.%fZ")
                trash_key = f"{parent}/__trash__/{stamp}-{deletion_id}/{basename}"
                row.status = "deleting"
                row.soft_deleted = True
                row.deleted_at = deleted_at
                row.purge_due_at = due_at
                row.purge_state = "pending_migration"
                row.purge_attempt_count = 0
                row.purge_next_retry_at = None
                row.purge_failure_reason = None
                row.deletion_principal_id = data.get("actor_principal_id")
                row.deletion_authorization_version = data.get("authorization_version")
                row.deletion_authorization_evidence = data.get("authorization_evidence")
                row.deletion_idempotency_key = data.get("idempotency_key")
                session.add(
                    FileDeletionRecordModel(
                        id=deletion_id,
                        tenant_id=tenant_id,
                        file_id=row.id,
                        storage_space_id=space_id,
                        application_id=row.application_id,
                        original_relative_key=original_relative_key,
                        original_physical_key=original_key,
                        trash_physical_key=trash_key,
                        content_length=row.content_length,
                        content_type=row.content_type,
                        etag=row.etag,
                        deleted_by=data.get("actor_principal_id"),
                        deleted_at=deleted_at,
                        purge_due_at=due_at,
                        status="requested",
                        idempotency_key=str(data.get("idempotency_key") or deletion_id),
                    )
                )
                outbox = await session.scalar(
                    select(FileRetentionOutboxModel)
                    .where(
                        FileRetentionOutboxModel.tenant_id == tenant_id,
                        FileRetentionOutboxModel.file_id == row.id,
                    )
                    .with_for_update()
                )
                if outbox is None:
                    outbox = FileRetentionOutboxModel(
                        tenant_id=tenant_id, file_id=row.id, action="schedule", due_at=due_at
                    )
                    session.add(outbox)
                else:
                    outbox.action = "schedule"
                    outbox.due_at = due_at
                    outbox.attempt_count = 0
                    outbox.next_retry_at = None
                    outbox.processed_at = None
                await session.flush()
                return _file_dict(row)
            return None

    async def restore_file(
        self, tenant_id: UUID, space_id: UUID, file_id: UUID, **data: Any
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.id == file_id,
                )
                .with_for_update()
            )
            if (
                row is not None
                and not row.soft_deleted
                and row.status == "available"
                and row.restore_idempotency_key == data.get("idempotency_key")
            ):
                return _file_dict(row)
            if (
                row is None
                or not row.soft_deleted
                or row.status != "deleted"
                or row.purge_due_at is None
                or row.purge_due_at <= datetime.now(UTC)
                or row.purge_state == "processing"
            ):
                return None
            if data.get("if_match") is None:
                from s3mp.common.api.etag import require_if_match

                require_if_match(None)
            if row.etag != data.get("if_match"):
                from s3mp.common.api.etag import check_etag

                check_etag(row.etag or "", str(data.get("if_match")))
            row.status = "available"
            row.soft_deleted = False
            row.deleted_at = None
            row.purge_due_at = None
            row.purge_state = None
            row.purge_next_retry_at = None
            row.purge_failure_reason = None
            row.restore_idempotency_key = data.get("idempotency_key")
            row.restored_at = datetime.now(UTC)
            outbox = await session.scalar(
                select(FileRetentionOutboxModel)
                .where(
                    FileRetentionOutboxModel.tenant_id == tenant_id,
                    FileRetentionOutboxModel.file_id == row.id,
                )
                .with_for_update()
            )
            if outbox is None:
                session.add(
                    FileRetentionOutboxModel(
                        tenant_id=tenant_id, file_id=row.id, action="unschedule"
                    )
                )
            else:
                outbox.action = "unschedule"
                outbox.due_at = None
                outbox.attempt_count = 0
                outbox.next_retry_at = None
                outbox.processed_at = None
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=data.get("actor_principal_id"),
                    action="file.restored",
                    resource_type="file_object",
                    resource_id=str(row.id),
                    details={
                        "request_id": data.get("request_id"),
                        "storage_space_id": str(space_id),
                    },
                )
            )
            await session.flush()
            return _file_dict(row)

    async def get_retained_file(
        self, tenant_id: UUID, space_id: UUID, file_id: UUID
    ) -> dict[str, Any] | None:
        """Internal management lookup; never used by application API read paths."""
        async with self._sf() as session:
            row = await session.scalar(
                select(FileObjectModel).where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.id == file_id,
                    FileObjectModel.soft_deleted.is_(True),
                )
            )
            return _file_dict(row) if row else None

    async def list_pending_deletions(self) -> list[dict[str, Any]]:
        async with self._sf() as session:
            rows = await session.scalars(
                select(FileObjectModel).where(
                    FileObjectModel.status == "deleting",
                    or_(
                        FileObjectModel.deletion_next_retry_at.is_(None),
                        FileObjectModel.deletion_next_retry_at <= datetime.now(UTC),
                    ),
                )
            )
            result = []
            for row in rows:
                deletion = await session.scalar(
                    select(FileDeletionRecordModel).where(
                        FileDeletionRecordModel.tenant_id == row.tenant_id,
                        FileDeletionRecordModel.file_id == row.id,
                    )
                )
                item = _file_dict(row)
                item["deletion_record"] = _deletion_dict(deletion) if deletion else None
                result.append(item)
            return result

    async def list_deletion_records(
        self,
        *,
        tenant_id: UUID | None = None,
        storage_space_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        after_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        async with self._sf() as session:
            query = (
                select(FileDeletionRecordModel)
                .order_by(FileDeletionRecordModel.id)
                .limit(limit)
            )
            if tenant_id is not None:
                query = query.where(FileDeletionRecordModel.tenant_id == tenant_id)
            if storage_space_id is not None:
                query = query.where(FileDeletionRecordModel.storage_space_id == storage_space_id)
            if status is not None:
                query = query.where(FileDeletionRecordModel.status == status)
            if after_id is not None:
                query = query.where(FileDeletionRecordModel.id > after_id)
            rows = await session.scalars(query)
            return [_deletion_public_dict(row) for row in rows]

    async def get_deletion_record(
        self, deletion_id: UUID, *, tenant_id: UUID | None = None
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            query = select(FileDeletionRecordModel).where(FileDeletionRecordModel.id == deletion_id)
            if tenant_id is not None:
                query = query.where(FileDeletionRecordModel.tenant_id == tenant_id)
            row = await session.scalar(query)
            return _deletion_public_dict(row) if row else None

    async def get_deletion_record_internal(
        self, deletion_id: UUID, *, tenant_id: UUID | None = None
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            query = select(FileDeletionRecordModel).where(FileDeletionRecordModel.id == deletion_id)
            if tenant_id is not None:
                query = query.where(FileDeletionRecordModel.tenant_id == tenant_id)
            row = await session.scalar(query)
            return _deletion_dict(row) if row else None

    async def get_storage_space_for_deletion(
        self, tenant_id: UUID, storage_space_id: UUID
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(StorageSpaceModel).where(
                    StorageSpaceModel.tenant_id == tenant_id,
                    StorageSpaceModel.id == storage_space_id,
                )
            )
            if row is None:
                return None
            return {
                "id": str(row.id),
                "tenant_id": str(row.tenant_id),
                "bucket": row.bucket,
                "root_prefix": row.root_prefix,
                "storage_namespace": row.storage_namespace,
                "profile_version": row.profile_version,
                "provider_target_version": row.provider_target_version,
            }

    async def finalize_file_trash_migration(self, tenant_id: UUID, file_id: UUID) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.id == file_id,
                    FileObjectModel.status == "deleting",
                    FileObjectModel.soft_deleted.is_(True),
                )
                .with_for_update()
            )
            deletion = await session.scalar(
                select(FileDeletionRecordModel)
                .where(
                    FileDeletionRecordModel.tenant_id == tenant_id,
                    FileDeletionRecordModel.file_id == file_id,
                )
                .with_for_update()
            )
            if row is None or deletion is None:
                return
            row.object_key = deletion.trash_physical_key
            row.status = "deleted"
            row.purge_state = "scheduled"
            deletion.status = "retained"
            await session.flush()

    async def record_delete_failure(
        self, tenant_id: UUID, file_id: UUID, max_attempts: int
    ) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.id == file_id,
                    FileObjectModel.status == "deleting",
                )
                .with_for_update()
            )
            if row is None:
                return
            row.deletion_attempt_count += 1
            deletion = await session.scalar(
                select(FileDeletionRecordModel)
                .where(
                    FileDeletionRecordModel.tenant_id == tenant_id,
                    FileDeletionRecordModel.file_id == file_id,
                )
                .with_for_update()
            )
            if row.deletion_attempt_count >= max_attempts:
                row.status = "delete_failed"
                row.deletion_failure_reason = "retry_exhausted"
                row.deletion_next_retry_at = None
                if deletion is not None:
                    deletion.status = "failed"
                    deletion.failure_reason = "retry_exhausted"
            else:
                row.deletion_failure_reason = "object_storage_unavailable"
                row.deletion_next_retry_at = datetime.now(UTC) + timedelta(
                    seconds=min(300, 2**row.deletion_attempt_count)
                )
                if deletion is not None:
                    deletion.status = "retrying"
                    deletion.attempt_count = row.deletion_attempt_count
                    deletion.next_retry_at = row.deletion_next_retry_at

    async def finalize_file_delete(self, tenant_id: UUID, file_id: UUID) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.id == file_id,
                    FileObjectModel.status == "deleting",
                )
                .with_for_update()
            )
            if row is None:
                return

            quota_filters = [
                (QuotaModel.application_id == row.application_id)
                if row.application_id is not None
                else (QuotaModel.storage_space_id == row.storage_space_id),
                ((QuotaModel.application_id.is_(None)) & (QuotaModel.storage_space_id.is_(None))),
            ]
            quotas = (
                await session.scalars(
                    select(QuotaModel)
                    .where(
                        QuotaModel.tenant_id == tenant_id,
                        or_(*quota_filters),
                    )
                    .order_by(QuotaModel.id)
                    .with_for_update()
                )
            ).all()
            for quota in quotas:
                idempotency_key = f"file-delete:{row.id}:{quota.id}"
                adjustment = await session.scalar(
                    select(QuotaAdjustmentModel).where(
                        QuotaAdjustmentModel.idempotency_key == idempotency_key
                    )
                )
                if adjustment is not None:
                    continue
                released = min(max(quota.used_bytes, 0), max(row.content_length, 0))
                quota.used_bytes -= released
                quota.measured_at = datetime.now(UTC)
                quota.consistency_status = "realtime"
                session.add(
                    QuotaAdjustmentModel(
                        tenant_id=tenant_id,
                        quota_id=quota.id,
                        file_object_id=row.id,
                        delta_bytes=-released,
                        reason="file_deleted",
                        idempotency_key=idempotency_key,
                        details={"content_length": row.content_length},
                    )
                )
                session.add(
                    AuditEventModel(
                        tenant_id=tenant_id,
                        actor_principal_id=row.deletion_principal_id,
                        action="quota.usage_released",
                        resource_type="quota",
                        resource_id=str(quota.id),
                        details={
                            "file_object_id": str(row.id),
                            "delta_bytes": -released,
                            "reason": "file_deleted",
                        },
                    )
                )
            row.status = "deleted"
            row.deleted_at = datetime.now(UTC)

    async def purge_deleted_files(self, retention_days: int, limit: int = 100) -> int:
        """Remove only retained tombstones whose quota release is evidenced.

        Provider objects are deliberately not touched here.  The deletion
        worker has already removed them before the tombstone was finalized;
        provider-only objects remain reconciliation evidence instead.
        """
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        async with self._sf.begin() as session:
            rows = (
                await session.scalars(
                    select(FileObjectModel)
                    .where(
                        FileObjectModel.status == "deleted",
                        FileObjectModel.soft_deleted.is_(False),
                        FileObjectModel.deleted_at.is_not(None),
                        FileObjectModel.deleted_at <= cutoff,
                        ~select(QuotaAdjustmentModel.id)
                        .where(QuotaAdjustmentModel.file_object_id == FileObjectModel.id)
                        .exists(),
                    )
                    .order_by(FileObjectModel.deleted_at)
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            ).all()
            for row in rows:
                await session.delete(row)
            return len(rows)

    async def list_retention_outbox(self, limit: int) -> list[dict[str, Any]]:
        """Return bounded pending schedule intents; acknowledgement is separate."""
        async with self._sf() as session:
            rows = await session.scalars(
                select(FileRetentionOutboxModel)
                .where(
                    FileRetentionOutboxModel.processed_at.is_(None),
                    or_(
                        FileRetentionOutboxModel.next_retry_at.is_(None),
                        FileRetentionOutboxModel.next_retry_at <= datetime.now(UTC),
                    ),
                )
                .order_by(FileRetentionOutboxModel.created_at)
                .limit(limit)
            )
            return [
                {
                    "id": str(row.id),
                    "tenant_id": str(row.tenant_id),
                    "file_id": str(row.file_id),
                    "action": row.action,
                    "due_at": row.due_at.isoformat() if row.due_at else None,
                }
                for row in rows
            ]

    async def acknowledge_retention_outbox(self, outbox_id: UUID, *, success: bool) -> None:
        async with self._sf.begin() as session:
            row = await session.get(FileRetentionOutboxModel, outbox_id, with_for_update=True)
            if row is None:
                return
            if success:
                row.processed_at = datetime.now(UTC)
                row.next_retry_at = None
                return
            row.attempt_count += 1
            row.next_retry_at = datetime.now(UTC) + timedelta(
                seconds=min(300, 2**row.attempt_count)
            )

    async def retention_reconciliation_candidates(self, limit: int) -> list[dict[str, Any]]:
        """Use the partial due-time index; never enumerate ordinary file rows."""
        async with self._sf() as session:
            rows = await session.scalars(
                select(FileObjectModel)
                .where(
                    FileObjectModel.soft_deleted.is_(True),
                    FileObjectModel.purge_due_at.is_not(None),
                    FileObjectModel.purge_state.in_(("scheduled", "retry_wait")),
                )
                .order_by(FileObjectModel.purge_due_at)
                .limit(limit)
            )
            return [_file_dict(row) for row in rows]

    async def claim_retained_file_for_purge(self, file_id: UUID) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel)
                .where(FileObjectModel.id == file_id)
                .with_for_update(skip_locked=True)
            )
            now = datetime.now(UTC)
            if (
                row is None
                or not row.soft_deleted
                or row.purge_due_at is None
                or row.purge_due_at > now
                or row.purge_state not in ("scheduled", "retry_wait")
                or (row.purge_next_retry_at is not None and row.purge_next_retry_at > now)
            ):
                return None
            row.purge_state = "processing"
            row.purge_attempt_count += 1
            row.purge_next_retry_at = None
            await session.flush()
            return _file_dict(row)

    async def finalize_retained_file_purge(self, tenant_id: UUID, file_id: UUID) -> None:
        """Release quota only after the provider object has been deleted."""
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.id == file_id,
                    FileObjectModel.soft_deleted.is_(True),
                    FileObjectModel.purge_state == "processing",
                )
                .with_for_update()
            )
            if row is None:
                return
            quota_filters = [
                (QuotaModel.application_id == row.application_id)
                if row.application_id is not None
                else (QuotaModel.storage_space_id == row.storage_space_id),
                ((QuotaModel.application_id.is_(None)) & (QuotaModel.storage_space_id.is_(None))),
            ]
            quotas = (
                await session.scalars(
                    select(QuotaModel)
                    .where(QuotaModel.tenant_id == tenant_id, or_(*quota_filters))
                    .with_for_update()
                )
            ).all()
            for quota in quotas:
                idempotency_key = f"file-retention-purge:{row.id}:{quota.id}"
                if await session.scalar(
                    select(QuotaAdjustmentModel).where(
                        QuotaAdjustmentModel.idempotency_key == idempotency_key
                    )
                ):
                    continue
                released = min(max(quota.used_bytes, 0), max(row.content_length, 0))
                quota.used_bytes -= released
                quota.measured_at = datetime.now(UTC)
                quota.consistency_status = "realtime"
                session.add(
                    QuotaAdjustmentModel(
                        tenant_id=tenant_id,
                        quota_id=quota.id,
                        file_object_id=row.id,
                        delta_bytes=-released,
                        reason="file_retention_purged",
                        idempotency_key=idempotency_key,
                        details={"content_length": row.content_length},
                    )
                )
            row.soft_deleted = False
            row.purge_state = "purged"
            row.purged_at = datetime.now(UTC)
            row.purge_due_at = None
            row.purge_next_retry_at = None
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=row.deletion_principal_id,
                    action="file.retention_purged",
                    resource_type="file_object",
                    resource_id=str(row.id),
                    details={
                        "storage_space_id": str(row.storage_space_id),
                        "attempt_count": row.purge_attempt_count,
                    },
                )
            )

    async def record_retained_purge_failure(self, file_id: UUID, max_attempts: int) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel).where(FileObjectModel.id == file_id).with_for_update()
            )
            if row is None or not row.soft_deleted or row.purge_state != "processing":
                return
            row.purge_state = "retry_wait"
            row.purge_failure_reason = "object_storage_unavailable"
            # Keep retrying indefinitely; the cap controls backoff, not retention loss.
            exponent = min(max_attempts, max(1, row.purge_attempt_count))
            row.purge_next_retry_at = datetime.now(UTC) + timedelta(seconds=min(3600, 2**exponent))

    async def create_operation(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            space = await session.scalar(
                select(StorageSpaceModel)
                .join(TenantModel, TenantModel.id == StorageSpaceModel.tenant_id)
                .where(
                    StorageSpaceModel.tenant_id == tenant_id,
                    StorageSpaceModel.id == space_id,
                    StorageSpaceModel.status == "active",
                    TenantModel.status == "active",
                )
            )
            if space is None:
                raise ValueError("storage space is not active")
            model = FileOperationModel(
                tenant_id=tenant_id,
                principal_id=UUID(data.get("principal_id", str(uuid4()))),
                membership_id=UUID(data["membership_id"]) if data.get("membership_id") else None,
                operation_type=data["operation_type"],
                source_key=data.get("source_key"),
                destination_key=data.get("destination_key"),
                keys=data.get("keys", []),
                idempotency_key=data.get("idempotency_key", str(uuid4())),
                status="queued",
                storage_space_id=space_id,
                application_id=(
                    UUID(data["application_id"]) if data.get("application_id") else None
                ),
                actor_application_id=(
                    UUID(data["actor_application_id"]) if data.get("actor_application_id") else None
                ),
                storage_namespace=data.get("storage_namespace"),
                profile_version=int(data.get("profile_version", 1)),
                authorization_version=int(data.get("authorization_version", 1)),
                provider_target_version=int(data.get("provider_target_version", 1)),
                authorization_evidence=data.get("authorization_evidence", {}),
            )
            session.add(model)
            await session.flush()
            occupied_keys, destination_keys = _operation_resource_keys(data)
            await self._occupy_operation_resources(
                session,
                tenant_id=tenant_id,
                space_id=space_id,
                operation=model,
                occupied_keys=occupied_keys,
                destination_keys=destination_keys,
            )
            session.add(
                FileOperationEventOutboxModel(
                    tenant_id=tenant_id,
                    operation_id=model.id,
                    event_type="file.operation.execute",
                    payload=_operation_event_payload(model),
                )
            )
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=model.principal_id,
                    action="file.operation_requested",
                    resource_type="file_operation",
                    resource_id=str(model.id),
                    details={"operation_type": model.operation_type},
                )
            )
            await session.flush()
            return _op_dict(model)

    async def create_rename_operation(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Reserve the target file and persist the rename intent atomically."""
        async with self._sf.begin() as session:
            source = await session.scalar(
                select(FileObjectModel)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.id == UUID(str(data["source_file_id"])),
                )
                .with_for_update()
            )
            if source is None or source.status != "available" or source.soft_deleted:
                raise ApiError("resource_not_found", "File not found", status_code=404)
            if data.get("if_match") is not None and source.etag != data["if_match"]:
                raise ApiError("precondition_failed", "File ETag does not match", status_code=412)

            existing = await session.scalar(
                select(FileOperationModel)
                .where(
                    FileOperationModel.tenant_id == tenant_id,
                    FileOperationModel.application_id == UUID(str(data["application_id"])),
                    FileOperationModel.operation_type == "rename",
                    FileOperationModel.idempotency_key == data["idempotency_key"],
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.request_fingerprint == data["request_fingerprint"]:
                    destination = await session.scalar(
                        select(FileObjectModel).where(
                            FileObjectModel.tenant_id == tenant_id,
                            FileObjectModel.id == existing.result_file_id,
                        )
                    )
                    result = _op_dict(existing)
                    if destination is not None:
                        result["result_file"] = _file_dict(destination)
                    return result
                raise ApiError(
                    "idempotency_conflict",
                    "Idempotency key was used for a different rename",
                    status_code=409,
                )
            if source.active_operation_id is not None:
                raise ApiError(
                    "file_operation_in_progress",
                    "File is occupied by an asynchronous operation",
                    status_code=409,
                )
            active = await session.scalar(
                select(FileOperationModel.id).where(
                    FileOperationModel.tenant_id == tenant_id,
                    FileOperationModel.source_file_id == source.id,
                    FileOperationModel.operation_type == "rename",
                    FileOperationModel.status.in_(
                        ("pending", "running", "retry_wait", "partial_failure")
                    ),
                )
            )
            if active is not None:
                raise ApiError(
                    "rename_conflict", "File already has an active rename", status_code=409
                )
            destination_key = str(data["destination_physical_key"])
            occupied = await session.scalar(
                select(FileObjectModel.id).where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.object_key == destination_key,
                    or_(
                        FileObjectModel.soft_deleted.is_(True),
                        FileObjectModel.status.in_(
                            ("available", "renaming", "rename_failed", "deleting", "delete_failed")
                        ),
                    ),
                )
            )
            if occupied is not None:
                raise ApiError(
                    "duplicate_resource", "Destination file already exists", status_code=409
                )
            destination = FileObjectModel(
                tenant_id=tenant_id,
                storage_space_id=space_id,
                application_id=source.application_id,
                storage_namespace=source.storage_namespace,
                profile_version=source.profile_version,
                object_key=destination_key,
                provider_target_version=source.provider_target_version,
                content_length=source.content_length,
                content_type=source.content_type,
                checksum=source.checksum,
                public_file_ref=data.get("result_file_ref"),
                metadata_json=source.metadata_json,
                # The provider returns the destination ETag only after the
                # asynchronous copy has completed.  It is not pre-issued.
                etag=None,
                status="renaming",
            )
            session.add(destination)
            await session.flush()
            operation = FileOperationModel(
                tenant_id=tenant_id,
                principal_id=UUID(str(data["principal_id"])),
                membership_id=(
                    UUID(str(data["membership_id"])) if data.get("membership_id") else None
                ),
                operation_type="rename",
                source_key=str(data["source_key"]),
                destination_key=str(data["destination_key"]),
                source_file_id=source.id,
                result_file_id=destination.id,
                keys=[],
                idempotency_key=str(data["idempotency_key"]),
                request_fingerprint=str(data["request_fingerprint"]),
                status="queued",
                storage_space_id=space_id,
                application_id=UUID(str(data["application_id"])),
                actor_application_id=(
                    UUID(str(data["actor_application_id"]))
                    if data.get("actor_application_id")
                    else None
                ),
                storage_namespace=data.get("storage_namespace"),
                profile_version=int(data.get("profile_version", 1)),
                authorization_version=int(data.get("authorization_version", 1)),
                provider_target_version=int(data.get("provider_target_version", 1)),
                authorization_evidence=data.get("authorization_evidence", {}),
            )
            session.add(operation)
            await session.flush()
            source.active_operation_id = operation.id
            source.operation_phase = "queued"
            destination.active_operation_id = operation.id
            destination.operation_phase = "queued"
            session.add(
                FileOperationEventOutboxModel(
                    tenant_id=tenant_id,
                    operation_id=operation.id,
                    event_type="file.operation.execute",
                    payload=_operation_event_payload(operation),
                )
            )
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=UUID(str(data["principal_id"])),
                    action="file.rename_requested",
                    resource_type="file_operation",
                    resource_id=str(operation.id),
                    details={
                        "request_id": data.get("request_id"),
                        "source_file_id": str(source.id),
                        "result_file_id": str(destination.id),
                        "destination_key_fingerprint": hashlib.sha256(
                            destination_key.encode("utf-8")
                        ).hexdigest(),
                    },
                )
            )
            result = _op_dict(operation)
            result["result_file"] = _file_dict(destination)
            return result

    async def replay_rename_operation(
        self, tenant_id: UUID, application_id: UUID, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Find a prior rename without requiring its (now deleted) source row."""
        async with self._sf() as session:
            operation = await session.scalar(
                select(FileOperationModel).where(
                    FileOperationModel.tenant_id == tenant_id,
                    FileOperationModel.application_id == application_id,
                    FileOperationModel.operation_type == "rename",
                    FileOperationModel.idempotency_key == idempotency_key,
                )
            )
            if operation is None:
                return None
            result = _op_dict(operation)
            if operation.result_file_id is not None:
                destination = await session.scalar(
                    select(FileObjectModel).where(
                        FileObjectModel.tenant_id == tenant_id,
                        FileObjectModel.id == operation.result_file_id,
                    )
                )
                if destination is not None:
                    result["result_file"] = _file_dict(destination)
            return result

    async def claim_outbox_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """Lease unpublished events briefly; this coordinates publishers, not work execution."""
        now = datetime.now(UTC)
        async with self._sf.begin() as session:
            rows = (
                await session.scalars(
                    select(FileOperationEventOutboxModel)
                    .where(
                        FileOperationEventOutboxModel.published_at.is_(None),
                        or_(
                            FileOperationEventOutboxModel.publish_lease_expires_at.is_(None),
                            FileOperationEventOutboxModel.publish_lease_expires_at < now,
                        ),
                    )
                    .order_by(FileOperationEventOutboxModel.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                row.publish_attempt_count += 1
                row.publish_lease_expires_at = now + timedelta(minutes=1)
            return [_outbox_dict(row) for row in rows]

    async def mark_outbox_published(self, event_id: UUID) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileOperationEventOutboxModel)
                .where(FileOperationEventOutboxModel.id == event_id)
                .with_for_update()
            )
            if row is not None:
                row.published_at = datetime.now(UTC)
                row.publish_lease_expires_at = None

    async def release_outbox_event(self, event_id: UUID) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileOperationEventOutboxModel)
                .where(FileOperationEventOutboxModel.id == event_id)
                .with_for_update()
            )
            if row is not None and row.published_at is None:
                row.publish_lease_expires_at = None

    async def start_broker_operation(
        self, tenant_id: UUID, operation_id: UUID
    ) -> dict[str, Any] | None:
        """Move an event-backed operation to processing exactly once per delivery."""
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileOperationModel)
                .where(
                    FileOperationModel.tenant_id == tenant_id, FileOperationModel.id == operation_id
                )
                .with_for_update()
            )
            if row is None or row.status not in {"queued", "retry_scheduled"}:
                return None
            row.status = "processing"
            row.attempt_count += 1
            now = datetime.now(UTC)
            files = (
                await session.scalars(
                    select(FileObjectModel)
                    .where(
                        FileObjectModel.tenant_id == tenant_id,
                        FileObjectModel.active_operation_id == row.id,
                    )
                    .with_for_update()
                )
            ).all()
            for file in files:
                file.operation_phase = "processing"
                file.processing_started_at = now
            await session.flush()
            return _op_dict(row)

    async def settle_broker_operation(
        self,
        tenant_id: UUID,
        operation_id: UUID,
        status: str,
        reason: str | None = None,
    ) -> None:
        """Persist outcome and release all durable mutation exclusion state before ack."""
        terminal = {"succeeded", "failed", "cancelled", "partial_failure", "dead_lettered"}
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileOperationModel)
                .where(
                    FileOperationModel.tenant_id == tenant_id, FileOperationModel.id == operation_id
                )
                .with_for_update()
            )
            if row is None:
                return
            files = (
                await session.scalars(
                    select(FileObjectModel)
                    .where(
                        FileObjectModel.tenant_id == tenant_id,
                        FileObjectModel.active_operation_id == operation_id,
                    )
                    .order_by(FileObjectModel.id)
                    .with_for_update()
                )
            ).all()
            if row.operation_type == "rename":
                source = next((file for file in files if file.id == row.source_file_id), None)
                destination = next((file for file in files if file.id == row.result_file_id), None)
                if status == "succeeded" and source is not None and destination is not None:
                    source.status, source.deleted_at = "deleted", datetime.now(UTC)
                    destination.status = "available"
                elif destination is not None and status in {"failed", "cancelled", "dead_lettered"}:
                    destination.status = "rename_failed"
            row.status, row.failure_reason = status, reason
            row.next_retry_at = None
            row.lease_owner, row.lease_expires_at = None, None
            if status in terminal:
                row.completed_at = datetime.now(UTC)
                for file in files:
                    file.active_operation_id = None
                    file.operation_phase = None
                    file.processing_started_at = None
                reservations = (
                    await session.scalars(
                        select(FileOperationResourceReservationModel)
                        .where(FileOperationResourceReservationModel.operation_id == operation_id)
                        .with_for_update()
                    )
                ).all()
                for reservation in reservations:
                    await session.delete(reservation)
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=row.principal_id,
                    action=f"file.operation_{status}",
                    resource_type="file_operation",
                    resource_id=str(row.id),
                    details={"reason": reason},
                )
            )

    async def record_rename_provider_result(
        self, tenant_id: UUID, operation_id: UUID, provider_etag: str | None
    ) -> None:
        """Persist the actual copy result before making the target available."""
        async with self._sf.begin() as session:
            operation = await session.scalar(
                select(FileOperationModel)
                .where(
                    FileOperationModel.tenant_id == tenant_id,
                    FileOperationModel.id == operation_id,
                    FileOperationModel.operation_type == "rename",
                )
                .with_for_update()
            )
            if operation is None or operation.result_file_id is None:
                return
            destination = await session.scalar(
                select(FileObjectModel)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.id == operation.result_file_id,
                )
                .with_for_update()
            )
            if destination is not None:
                destination.etag = provider_etag

    async def schedule_broker_retry(
        self, tenant_id: UUID, operation_id: UUID, reason: str | None = None
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileOperationModel)
                .where(
                    FileOperationModel.tenant_id == tenant_id, FileOperationModel.id == operation_id
                )
                .with_for_update()
            )
            if row is None or row.status != "processing":
                return None
            row.status, row.failure_reason = "retry_scheduled", reason
            row.next_retry_at = datetime.now(UTC)
            files = (
                await session.scalars(
                    select(FileObjectModel).where(FileObjectModel.active_operation_id == row.id)
                )
            ).all()
            for file in files:
                file.operation_phase = "retry_scheduled"
                file.processing_started_at = None
            return _op_dict(row)

    async def operation_file_ids(self, tenant_id: UUID, operation_id: UUID) -> list[UUID]:
        async with self._sf() as session:
            return list(
                await session.scalars(
                    select(FileObjectModel.id)
                    .where(
                        FileObjectModel.tenant_id == tenant_id,
                        FileObjectModel.active_operation_id == operation_id,
                    )
                    .order_by(FileObjectModel.storage_space_id, FileObjectModel.id)
                )
            )

    async def recover_timed_out_operations(
        self, timeout_seconds: int, max_recoveries: int, limit: int = 100
    ) -> int:
        """Indexed exceptional recovery; it never claims ordinary queued work."""
        cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
        recovered = 0
        async with self._sf.begin() as session:
            rows = (
                (
                    await session.scalars(
                        select(FileOperationModel)
                        .join(
                            FileObjectModel,
                            (FileObjectModel.tenant_id == FileOperationModel.tenant_id)
                            & (FileObjectModel.active_operation_id == FileOperationModel.id),
                        )
                        .where(
                            FileOperationModel.status == "processing",
                            FileObjectModel.processing_started_at < cutoff,
                        )
                        .order_by(FileObjectModel.processing_started_at)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                .unique()
                .all()
            )
            for row in rows:
                if row.recovery_attempt_count >= max_recoveries:
                    row.status, row.failure_reason = "dead_lettered", "processing_timeout"
                    row.completed_at = datetime.now(UTC)
                    continue
                row.recovery_attempt_count += 1
                row.status, row.failure_reason = "queued", "processing_timeout_recovery"
                files = (
                    await session.scalars(
                        select(FileObjectModel)
                        .where(FileObjectModel.active_operation_id == row.id)
                        .with_for_update()
                    )
                ).all()
                for file in files:
                    file.operation_phase, file.processing_started_at = "queued", None
                session.add(
                    FileOperationEventOutboxModel(
                        tenant_id=row.tenant_id,
                        operation_id=row.id,
                        event_type="file.operation.execute",
                        payload=_operation_event_payload(row),
                    )
                )
                recovered += 1
        return recovered

    async def record_dead_letter_event(
        self, tenant_id: UUID, operation_id: UUID | None, details: dict[str, Any]
    ) -> None:
        async with self._sf.begin() as session:
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=None,
                    action="file.operation_dead_letter_received",
                    resource_type="file_operation",
                    resource_id=str(operation_id) if operation_id else None,
                    details=details,
                )
            )

    async def replay_dead_letter_operation(
        self, tenant_id: UUID, operation_id: UUID, replay_of_event_id: UUID
    ) -> dict[str, Any] | None:
        """Create a linked delivery intent instead of republishing raw DLQ data."""
        async with self._sf.begin() as session:
            operation = await session.scalar(
                select(FileOperationModel)
                .where(
                    FileOperationModel.tenant_id == tenant_id,
                    FileOperationModel.id == operation_id,
                    FileOperationModel.status.in_(("dead_lettered", "partial_failure")),
                )
                .with_for_update()
            )
            if operation is None:
                return None
            operation.status, operation.failure_reason = "queued", None
            operation.completed_at = None
            operation.replay_of_event_id = replay_of_event_id
            session.add(
                FileOperationEventOutboxModel(
                    tenant_id=tenant_id,
                    operation_id=operation_id,
                    event_type="file.operation.execute",
                    payload=_operation_event_payload(operation),
                    replay_of_event_id=replay_of_event_id,
                )
            )
            return _op_dict(operation)

    async def enqueue_legacy_operations(self, limit: int = 1_000) -> int:
        """One-time cutover bridge; callers must stop the legacy polling worker first."""
        now = datetime.now(UTC)
        migrated = 0
        async with self._sf.begin() as session:
            rows = (
                await session.scalars(
                    select(FileOperationModel)
                    .where(
                        or_(
                            FileOperationModel.status.in_(("pending", "retry_wait")),
                            (FileOperationModel.status == "running")
                            & (FileOperationModel.lease_expires_at < now),
                        )
                    )
                    .order_by(FileOperationModel.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for operation in rows:
                operation.status, operation.next_retry_at = "queued", None
                operation.lease_owner, operation.lease_expires_at = None, None
                existing = await session.scalar(
                    select(FileOperationEventOutboxModel.id).where(
                        FileOperationEventOutboxModel.operation_id == operation.id
                    )
                )
                if existing is None:
                    session.add(
                        FileOperationEventOutboxModel(
                            tenant_id=operation.tenant_id,
                            operation_id=operation.id,
                            event_type="file.operation.execute",
                            payload=_operation_event_payload(operation),
                        )
                    )
                migrated += 1
        return migrated

    async def _occupy_operation_resources(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        space_id: UUID,
        operation: FileOperationModel,
        occupied_keys: list[str],
        destination_keys: list[str],
    ) -> None:
        """Claim file rows and destination names in one operation-creation transaction."""
        all_keys = sorted(set(occupied_keys + destination_keys))
        rows = (
            await session.scalars(
                select(FileObjectModel)
                .where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.object_key.in_(all_keys),
                )
                .order_by(FileObjectModel.id)
                .with_for_update()
            )
        ).all()
        rows_by_key = {row.object_key: row for row in rows}
        for key in occupied_keys:
            row = rows_by_key.get(key)
            if row is None or row.status != "available" or row.soft_deleted:
                raise ApiError("resource_not_found", "File not found", status_code=404)
            if row.active_operation_id is not None:
                raise ApiError(
                    "file_operation_in_progress",
                    "File is occupied by an asynchronous operation",
                    status_code=409,
                )
        for key in destination_keys:
            if rows_by_key.get(key) is not None:
                raise ApiError(
                    "duplicate_resource",
                    "Destination file already exists",
                    status_code=409,
                )
        for key in occupied_keys:
            row = rows_by_key.get(key)
            if row is not None:
                row.active_operation_id = operation.id
                row.operation_phase = "queued"
        for key in destination_keys:
            session.add(
                FileOperationResourceReservationModel(
                    tenant_id=tenant_id,
                    storage_space_id=space_id,
                    object_key=key,
                    operation_id=operation.id,
                )
            )
        try:
            await session.flush()
        except IntegrityError as exc:
            raise ApiError(
                "file_operation_in_progress",
                "Destination key is reserved by an asynchronous operation",
                status_code=409,
            ) from exc

    async def get_operation(self, tenant_id: UUID, op_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(FileOperationModel)
                .join(
                    StorageSpaceModel,
                    (StorageSpaceModel.tenant_id == FileOperationModel.tenant_id)
                    & (StorageSpaceModel.id == FileOperationModel.storage_space_id),
                )
                .join(TenantModel, TenantModel.id == FileOperationModel.tenant_id)
                .where(
                    FileOperationModel.tenant_id == tenant_id,
                    FileOperationModel.id == op_id,
                    StorageSpaceModel.status == "active",
                    TenantModel.status == "active",
                )
            )
            return _op_dict(row) if row else None

    async def operation_metrics(self) -> dict[str, int]:
        now = datetime.now(UTC)
        async with self._sf() as session:
            rows = await session.execute(
                select(FileOperationModel.status, func.count()).group_by(FileOperationModel.status)
            )
            metrics = {f"status_{status}": int(count) for status, count in rows}
            metrics["stale_leases"] = int(
                await session.scalar(
                    select(func.count())
                    .select_from(FileOperationModel)
                    .where(
                        FileOperationModel.status == "running",
                        FileOperationModel.lease_expires_at < now,
                    )
                )
                or 0
            )
            metrics["backlog"] = sum(
                metrics.get(f"status_{status}", 0)
                for status in ("pending", "retry_wait", "running")
            )
            return metrics

    # ── Uploads ────────────────────────────────────────────────────────────

    async def create_upload(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            space = await session.scalar(
                select(StorageSpaceModel)
                .join(TenantModel, TenantModel.id == StorageSpaceModel.tenant_id)
                .where(
                    StorageSpaceModel.tenant_id == tenant_id,
                    StorageSpaceModel.id == space_id,
                    StorageSpaceModel.status == "active",
                    TenantModel.status == "active",
                )
            )
            if space is None:
                raise ValueError("storage space is not active")
            model = UploadSessionModel(
                tenant_id=tenant_id,
                principal_id=UUID(data["principal_id"]),
                membership_id=UUID(data["membership_id"]) if data.get("membership_id") else None,
                storage_space_id=space_id,
                application_id=(
                    UUID(str(data["application_id"]))
                    if data.get("application_id")
                    else space.application_id
                ),
                actor_application_id=(
                    UUID(str(data["actor_application_id"]))
                    if data.get("actor_application_id")
                    else None
                ),
                storage_namespace=data.get("storage_namespace") or space.storage_namespace,
                profile_version=int(data.get("profile_version", space.profile_version)),
                object_key=data["object_key"],
                provider_target_version=int(data.get("provider_target_version", 1)),
                declared_length=data["content_length"],
                content_type=data["content_type"],
                checksum=data.get("checksum"),
                metadata_json=data.get("metadata"),
                expires_at=data["expires_at"],
                status="pending",
            )
            session.add(model)
            await session.flush()
            return _upload_dict(model)

    async def get_upload(self, tenant_id: UUID, upload_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(UploadSessionModel)
                .join(
                    StorageSpaceModel,
                    (StorageSpaceModel.tenant_id == UploadSessionModel.tenant_id)
                    & (StorageSpaceModel.id == UploadSessionModel.storage_space_id),
                )
                .join(TenantModel, TenantModel.id == UploadSessionModel.tenant_id)
                .where(
                    UploadSessionModel.tenant_id == tenant_id,
                    UploadSessionModel.id == upload_id,
                    StorageSpaceModel.status == "active",
                    TenantModel.status == "active",
                )
            )
            return _upload_dict(row) if row else None

    async def expire_upload(self, tenant_id: UUID, upload_id: UUID) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(UploadSessionModel)
                .where(
                    UploadSessionModel.tenant_id == tenant_id,
                    UploadSessionModel.id == upload_id,
                )
                .with_for_update()
            )
            if row is not None and row.status == "pending":
                row.status = "expired"

    async def complete_upload(
        self, tenant_id: UUID, upload_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(UploadSessionModel)
                .where(
                    UploadSessionModel.tenant_id == tenant_id,
                    UploadSessionModel.id == upload_id,
                )
                .with_for_update()
            )
            if row is None:
                raise ValueError("upload not found")
            row.status = "completed"
            row.completed_at = datetime.now(UTC)
            # Create file_object record so the file is visible in list_files
            file_obj = FileObjectModel(
                tenant_id=tenant_id,
                storage_space_id=row.storage_space_id,
                application_id=row.application_id,
                storage_namespace=row.storage_namespace,
                profile_version=row.profile_version,
                object_key=row.object_key,
                provider_target_version=row.provider_target_version,
                content_length=row.declared_length,
                content_type=row.content_type,
                checksum=data.get("checksum") or row.checksum,
                public_file_ref=generate_file_ref(
                    tenant_id=tenant_id,
                    application_id=row.application_id,
                    relative_key=row.object_key,
                    metadata=row.metadata_json,
                    checksum=data.get("checksum") or row.checksum,
                ),
                metadata_json=row.metadata_json,
                etag=data.get("etag"),
            )
            session.add(file_obj)
            await session.flush()
            result = _upload_dict(row)
            result["file_object"] = _file_dict(file_obj)
            return result

    # ── Multipart ──────────────────────────────────────────────────────────

    async def create_multipart(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            space = await session.scalar(
                select(StorageSpaceModel)
                .join(TenantModel, TenantModel.id == StorageSpaceModel.tenant_id)
                .where(
                    StorageSpaceModel.tenant_id == tenant_id,
                    StorageSpaceModel.id == space_id,
                    StorageSpaceModel.status == "active",
                    TenantModel.status == "active",
                )
            )
            if space is None:
                raise ValueError("storage space is not active")
            model = MultipartSessionModel(
                tenant_id=tenant_id,
                principal_id=UUID(data["principal_id"]),
                membership_id=UUID(data["membership_id"]) if data.get("membership_id") else None,
                storage_space_id=space_id,
                application_id=(
                    UUID(str(data["application_id"]))
                    if data.get("application_id")
                    else space.application_id
                ),
                actor_application_id=(
                    UUID(str(data["actor_application_id"]))
                    if data.get("actor_application_id")
                    else None
                ),
                storage_namespace=data.get("storage_namespace") or space.storage_namespace,
                profile_version=int(data.get("profile_version", space.profile_version)),
                object_key=data["object_key"],
                provider_target_version=int(data.get("provider_target_version", 1)),
                declared_length=data["content_length"],
                content_type=data["content_type"],
                checksum=data.get("checksum"),
                metadata_json=data.get("metadata"),
                quota_reservation_id=uuid4(),
                expires_at=data["expires_at"],
                status="pending",
            )
            session.add(model)
            await session.flush()
            return _mp_dict(model)

    async def set_multipart_provider_id(
        self, tenant_id: UUID, multipart_id: UUID, provider_upload_id: str
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartSessionModel)
                .where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == multipart_id,
                )
                .with_for_update()
            )
            if row is None:
                raise ValueError("multipart not found")
            row.provider_upload_id = provider_upload_id
            await session.flush()
            return _mp_dict(row)

    async def get_multipart(self, tenant_id: UUID, mp_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(MultipartSessionModel)
                .join(
                    StorageSpaceModel,
                    (StorageSpaceModel.tenant_id == MultipartSessionModel.tenant_id)
                    & (StorageSpaceModel.id == MultipartSessionModel.storage_space_id),
                )
                .join(TenantModel, TenantModel.id == MultipartSessionModel.tenant_id)
                .where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == mp_id,
                    StorageSpaceModel.status == "active",
                    TenantModel.status == "active",
                )
            )
            return _mp_dict(row) if row else None

    async def expire_multipart(self, tenant_id: UUID, mp_id: UUID) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartSessionModel)
                .where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == mp_id,
                )
                .with_for_update()
            )
            if row is not None and row.status == "pending":
                row.status = "expired"

    async def abort_multipart(
        self, tenant_id: UUID, mp_id: UUID, *, idempotency_key: str | None = None
    ) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartSessionModel)
                .where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == mp_id,
                )
                .with_for_update()
            )
            if row is not None:
                row.status = "aborted"
                await session.flush()

    async def list_multipart_parts(self, tenant_id: UUID, mp_id: UUID) -> list[dict[str, Any]]:
        async with self._sf() as session:
            rows = await session.scalars(
                select(MultipartPartModel)
                .where(
                    MultipartPartModel.tenant_id == tenant_id,
                    MultipartPartModel.multipart_session_id == mp_id,
                )
                .order_by(MultipartPartModel.part_number)
            )
            return [_part_dict(r) for r in rows]

    async def record_multipart_part(
        self, tenant_id: UUID, mp_id: UUID, part_number: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartPartModel)
                .where(
                    MultipartPartModel.tenant_id == tenant_id,
                    MultipartPartModel.multipart_session_id == mp_id,
                    MultipartPartModel.part_number == part_number,
                )
                .with_for_update()
            )
            if row is None:
                row = MultipartPartModel(
                    tenant_id=tenant_id,
                    multipart_session_id=mp_id,
                    part_number=part_number,
                    etag=data["etag"],
                    content_length=data["content_length"],
                    idempotency_key=data.get("idempotency_key"),
                    content_sha256=data.get("content_sha256"),
                )
                session.add(row)
            else:
                row.etag = data["etag"]
                row.content_length = data["content_length"]
                row.idempotency_key = data.get("idempotency_key")
                row.content_sha256 = data.get("content_sha256")
            await session.flush()
            return _part_dict(row)

    async def complete_multipart(
        self, tenant_id: UUID, mp_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartSessionModel)
                .where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == mp_id,
                )
                .with_for_update()
            )
            if row is None:
                raise ValueError("multipart not found")
            row.status = "completed"
            file_obj = FileObjectModel(
                tenant_id=tenant_id,
                storage_space_id=row.storage_space_id,
                application_id=row.application_id,
                storage_namespace=row.storage_namespace,
                profile_version=row.profile_version,
                object_key=row.object_key,
                provider_target_version=row.provider_target_version,
                content_length=data["content_length"],
                content_type=data["content_type"],
                checksum=data.get("checksum"),
                public_file_ref=generate_file_ref(
                    tenant_id=tenant_id,
                    application_id=row.application_id,
                    relative_key=row.object_key,
                    metadata=row.metadata_json,
                    checksum=data.get("checksum") or row.checksum,
                ),
                metadata_json=row.metadata_json,
                etag=data.get("etag"),
            )
            session.add(file_obj)
            await session.flush()
            result = _mp_dict(row)
            result["file_object"] = _file_dict(file_obj)
            return result


def _validate_delete_etag(
    current_etag: str | None, supplied_etag: str | None, *, is_file_ref: bool
) -> None:
    """Apply the legacy ETag precondition without leaking it into file_ref deletes."""
    if is_file_ref:
        return
    from s3mp.common.api.etag import check_etag, require_if_match

    if supplied_etag is None:
        require_if_match(None)
    if current_etag != supplied_etag:
        check_etag(current_etag or "", str(supplied_etag))


def _file_dict(m: FileObjectModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "storage_space_id": str(m.storage_space_id),
        "application_id": str(m.application_id) if m.application_id else None,
        "storage_namespace": m.storage_namespace,
        "profile_version": m.profile_version,
        "object_key": m.object_key,
        "provider_target_version": m.provider_target_version,
        "content_length": m.content_length,
        "content_type": m.content_type,
        "etag": m.etag,
        "checksum": m.checksum,
        "file_ref": m.public_file_ref,
        "metadata": m.metadata_json,
        "record_etag": _record_etag(m),
        "status": m.status,
        "deletion_attempt_count": m.deletion_attempt_count,
        "deletion_principal_id": str(m.deletion_principal_id) if m.deletion_principal_id else None,
        "deletion_authorization_version": m.deletion_authorization_version,
        "deletion_authorization_evidence": m.deletion_authorization_evidence,
        "deletion_idempotency_key": m.deletion_idempotency_key,
        "soft_deleted": m.soft_deleted,
        "purge_due_at": m.purge_due_at.isoformat() if m.purge_due_at else None,
        "purge_state": m.purge_state,
        "purge_attempt_count": m.purge_attempt_count,
        "purge_next_retry_at": m.purge_next_retry_at.isoformat() if m.purge_next_retry_at else None,
        "purged_at": m.purged_at.isoformat() if m.purged_at else None,
        "restore_idempotency_key": m.restore_idempotency_key,
        "restored_at": m.restored_at.isoformat() if m.restored_at else None,
        "created_at": m.created_at.isoformat(),
    }


def _deletion_dict(m: FileDeletionRecordModel | None) -> dict[str, Any] | None:
    if m is None:
        return None
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "file_id": str(m.file_id),
        "storage_space_id": str(m.storage_space_id),
        "application_id": str(m.application_id) if m.application_id else None,
        "original_relative_key": m.original_relative_key,
        "original_physical_key": m.original_physical_key,
        "trash_physical_key": m.trash_physical_key,
        "content_length": m.content_length,
        "content_type": m.content_type,
        "etag": m.etag,
        "deleted_by": str(m.deleted_by) if m.deleted_by else None,
        "deleted_at": m.deleted_at.isoformat(),
        "purge_due_at": m.purge_due_at.isoformat(),
        "status": m.status,
        "attempt_count": m.attempt_count,
        "next_retry_at": m.next_retry_at.isoformat() if m.next_retry_at else None,
        "failure_reason": m.failure_reason,
        "purged_at": m.purged_at.isoformat() if m.purged_at else None,
    }


def _deletion_public_dict(m: FileDeletionRecordModel) -> dict[str, Any]:
    """Expose provenance without exposing provider-owned physical keys."""
    value = _deletion_dict(m)
    assert value is not None
    value.pop("original_physical_key", None)
    value.pop("trash_physical_key", None)
    return value


def _record_etag(m: FileObjectModel) -> str:
    return hashlib.sha256(f"file-record:{m.id}:{m.record_version}".encode()).hexdigest()[:32]


def _upload_dict(m: UploadSessionModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "principal_id": str(m.principal_id),
        "object_key": m.object_key,
        "membership_id": str(m.membership_id) if m.membership_id else None,
        "provider_target_version": m.provider_target_version,
        "storage_space_id": str(m.storage_space_id),
        "application_id": str(m.application_id) if m.application_id else None,
        "storage_namespace": m.storage_namespace,
        "profile_version": m.profile_version,
        "content_length": m.declared_length,
        "content_type": m.content_type,
        "status": m.status,
        "checksum": m.checksum,
        "metadata": m.metadata_json,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
    }


def _mp_dict(m: MultipartSessionModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "principal_id": str(m.principal_id),
        "object_key": m.object_key,
        "membership_id": str(m.membership_id) if m.membership_id else None,
        "provider_target_version": m.provider_target_version,
        "storage_space_id": str(m.storage_space_id),
        "application_id": str(m.application_id) if m.application_id else None,
        "storage_namespace": m.storage_namespace,
        "profile_version": m.profile_version,
        "content_length": m.declared_length,
        "content_type": m.content_type,
        "checksum": m.checksum,
        "metadata": m.metadata_json,
        "status": m.status,
        "provider_upload_id": m.provider_upload_id,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
    }


def _part_dict(m: MultipartPartModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "part_number": m.part_number,
        "etag": m.etag,
        "content_length": m.content_length,
        "idempotency_key": m.idempotency_key,
        "content_sha256": m.content_sha256,
    }


def _op_dict(m: FileOperationModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "principal_id": str(m.principal_id),
        "membership_id": str(m.membership_id) if m.membership_id else None,
        "operation_type": m.operation_type,
        "status": m.status,
        "source_key": m.source_key,
        "destination_key": m.destination_key,
        "source_file_id": str(m.source_file_id) if m.source_file_id else None,
        "result_file_id": str(m.result_file_id) if m.result_file_id else None,
        "keys": list(m.keys or ()),
        "idempotency_key": m.idempotency_key,
        "failure_reason": m.failure_reason,
        "storage_space_id": str(m.storage_space_id) if m.storage_space_id else None,
        "application_id": str(m.application_id) if m.application_id else None,
        "storage_namespace": m.storage_namespace,
        "profile_version": m.profile_version,
        "authorization_version": m.authorization_version,
        "provider_target_version": m.provider_target_version,
        "authorization_evidence": m.authorization_evidence or {},
        "attempt_count": m.attempt_count,
        "recovery_attempt_count": m.recovery_attempt_count,
        "replay_of_event_id": str(m.replay_of_event_id) if m.replay_of_event_id else None,
        "lease_owner": m.lease_owner,
        "lease_expires_at": m.lease_expires_at.isoformat() if m.lease_expires_at else None,
        "next_retry_at": m.next_retry_at.isoformat() if m.next_retry_at else None,
        "completed_at": m.completed_at.isoformat() if m.completed_at else None,
        "created_at": m.created_at.isoformat(),
    }


def _operation_resource_keys(data: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return physical source/target keys subject to durable mutation exclusion."""
    operation_type = str(data["operation_type"])
    if operation_type == "delete":
        return sorted(set(data.get("physical_keys") or ())), []
    source = data.get("source_physical_key")
    destination = data.get("destination_physical_key")
    return ([str(source)] if source else []), ([str(destination)] if destination else [])


def _operation_event_payload(operation: FileOperationModel) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_id": str(uuid4()),
        "operation_id": str(operation.id),
        "tenant_id": str(operation.tenant_id),
        "event_type": "file.operation.execute",
        "created_at": datetime.now(UTC).isoformat(),
    }


def _outbox_dict(m: FileOperationEventOutboxModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "operation_id": str(m.operation_id),
        "event_type": m.event_type,
        "payload": dict(m.payload or {}),
        "publish_attempt_count": m.publish_attempt_count,
    }
