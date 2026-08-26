"""SQLAlchemy repository for file objects, uploads, multipart sessions, and operations."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.common.errors import ApiError
from s3mp.files.domain.file_status import FileObjectStatus
from s3mp.files.infrastructure.models import (
    FileObjectModel,
    FileOperationModel,
    FileRetentionOutboxModel,
    MultipartPartModel,
    MultipartSessionModel,
    UploadSessionModel,
)
from s3mp.governance.infrastructure.models import QuotaAdjustmentModel, QuotaModel
from s3mp.storage.infrastructure.models import StorageSpaceModel
from s3mp.tenant.infrastructure.models import TenantModel


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
                if data.get("if_match") is None:
                    from s3mp.common.api.etag import require_if_match

                    require_if_match(None)
                if row.etag != data.get("if_match"):
                    from s3mp.common.api.etag import check_etag

                    check_etag(row.etag or "", str(data.get("if_match")))
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
                row.status = "deleted"
                row.soft_deleted = True
                row.deleted_at = datetime.now(UTC)
                row.purge_due_at = due_at
                row.purge_state = "scheduled"
                row.purge_attempt_count = 0
                row.purge_next_retry_at = None
                row.purge_failure_reason = None
                row.deletion_principal_id = data.get("actor_principal_id")
                row.deletion_authorization_version = data.get("authorization_version")
                row.deletion_authorization_evidence = data.get("authorization_evidence")
                row.deletion_idempotency_key = data.get("idempotency_key")
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
            return [_file_dict(row) for row in rows]

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
            if row.deletion_attempt_count >= max_attempts:
                row.status = "delete_failed"
                row.deletion_failure_reason = "retry_exhausted"
                row.deletion_next_retry_at = None
            else:
                row.deletion_failure_reason = "object_storage_unavailable"
                row.deletion_next_retry_at = datetime.now(UTC) + timedelta(
                    seconds=min(300, 2**row.deletion_attempt_count)
                )

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
                status="pending",
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
            if source.etag != data["if_match"]:
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
                    return _op_dict(existing)
                raise ApiError(
                    "idempotency_conflict",
                    "Idempotency key was used for a different rename",
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
                etag=source.etag,
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
                status="pending",
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
            return _op_dict(operation)

    async def claim_operations(self, worker_id: str, limit: int = 10) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        async with self._sf.begin() as session:
            rows = await session.scalars(
                select(FileOperationModel)
                .where(
                    or_(
                        FileOperationModel.status.in_(("pending", "retry_wait")),
                        (FileOperationModel.status == "running")
                        & (FileOperationModel.lease_expires_at < now),
                    ),
                    or_(
                        FileOperationModel.next_retry_at.is_(None),
                        FileOperationModel.next_retry_at <= now,
                    ),
                )
                .order_by(FileOperationModel.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            claimed = list(rows)
            for row in claimed:
                row.status = "running"
                row.lease_owner = worker_id
                row.lease_expires_at = now + timedelta(minutes=1)
                row.attempt_count += 1
            await session.flush()
            return [_op_dict(row) for row in claimed]

    async def renew_operation_lease(
        self, tenant_id: UUID, operation_id: UUID, worker_id: str
    ) -> bool:
        """Extend a lease only while it is still owned by this worker."""
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileOperationModel)
                .where(
                    FileOperationModel.tenant_id == tenant_id,
                    FileOperationModel.id == operation_id,
                    FileOperationModel.status == "running",
                    FileOperationModel.lease_owner == worker_id,
                )
                .with_for_update()
            )
            if row is None:
                return False
            row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=1)
            return True

    async def finish_operation(
        self, tenant_id: UUID, operation_id: UUID, status: str, reason: str | None = None
    ) -> None:
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
            if status == "retry_wait":
                # A transient provider failure must not create a hot retry loop.
                # Five attempts is intentionally bounded; an operator can inspect
                # the durable failed row instead of silently retrying forever.
                if row.attempt_count >= 5:
                    status = "failed"
                    reason = "retry_exhausted"
                else:
                    row.next_retry_at = datetime.now(UTC) + timedelta(
                        seconds=min(300, 2**row.attempt_count)
                    )
            else:
                row.next_retry_at = None
            row.status, row.failure_reason = status, reason
            row.lease_owner, row.lease_expires_at = None, None
            if status in {"succeeded", "failed", "partial_failure", "cancelled"}:
                row.completed_at = datetime.now(UTC)

    async def finish_rename_operation(
        self, tenant_id: UUID, operation_id: UUID, status: str, reason: str | None = None
    ) -> None:
        """Settle catalog visibility only when provider-side rename truly completed."""
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileOperationModel)
                .where(
                    FileOperationModel.tenant_id == tenant_id,
                    FileOperationModel.id == operation_id,
                )
                .with_for_update()
            )
            if row is None:
                return
            source = (
                await session.scalar(
                    select(FileObjectModel)
                    .where(
                        FileObjectModel.tenant_id == tenant_id,
                        FileObjectModel.id == row.source_file_id,
                    )
                    .with_for_update()
                )
                if row.source_file_id
                else None
            )
            destination = (
                await session.scalar(
                    select(FileObjectModel)
                    .where(
                        FileObjectModel.tenant_id == tenant_id,
                        FileObjectModel.id == row.result_file_id,
                    )
                    .with_for_update()
                )
                if row.result_file_id
                else None
            )
            if status == "succeeded" and source is not None and destination is not None:
                source.status, source.deleted_at = "deleted", datetime.now(UTC)
                destination.status = "available"
            elif destination is not None and status == "failed":
                destination.status = "rename_failed"
            if status == "retry_wait":
                if row.attempt_count >= 5:
                    status, reason = "failed", "retry_exhausted"
                else:
                    row.next_retry_at = datetime.now(UTC) + timedelta(
                        seconds=min(300, 2**row.attempt_count)
                    )
            else:
                row.next_retry_at = None
            row.status, row.failure_reason = status, reason
            row.lease_owner, row.lease_expires_at = None, None
            if status in {"succeeded", "failed", "partial_failure", "cancelled"}:
                row.completed_at = datetime.now(UTC)
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=row.principal_id,
                    action=f"file.rename_{status}",
                    resource_type="file_operation",
                    resource_id=str(row.id),
                    details={"reason": reason, "result_file_id": str(row.result_file_id)},
                )
            )

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
                etag=data.get("etag"),
            )
            session.add(file_obj)
            await session.flush()
            result = _mp_dict(row)
            result["file_object"] = _file_dict(file_obj)
            return result


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
        "lease_owner": m.lease_owner,
        "lease_expires_at": m.lease_expires_at.isoformat() if m.lease_expires_at else None,
        "next_retry_at": m.next_retry_at.isoformat() if m.next_retry_at else None,
        "completed_at": m.completed_at.isoformat() if m.completed_at else None,
        "created_at": m.created_at.isoformat(),
    }
