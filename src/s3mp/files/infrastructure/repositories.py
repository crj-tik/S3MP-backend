"""SQLAlchemy repository for file objects, uploads, multipart sessions, and operations."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.files.infrastructure.models import (
    FileObjectModel,
    FileOperationModel,
    MultipartPartModel,
    MultipartSessionModel,
    UploadSessionModel,
)


class SqlAlchemyFileStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Files ──────────────────────────────────────────────────────────────

    async def list_files(
        self, tenant_id: UUID, space_id: UUID, prefix: str
    ) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = select(FileObjectModel).where(
                FileObjectModel.tenant_id == tenant_id,
                FileObjectModel.storage_space_id == space_id,
                FileObjectModel.status == "available",
            )
            if prefix:
                stmt = stmt.where(FileObjectModel.object_key.startswith(prefix))
            rows = (await session.scalars(stmt.order_by(FileObjectModel.object_key))).all()
            return [_file_dict(r) for r in rows]

    async def get_file(
        self, tenant_id: UUID, space_id: UUID, file_id: UUID
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(FileObjectModel).where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.id == file_id,
                    FileObjectModel.status == "available",
                )
            )
            return _file_dict(row) if row else None

    async def delete_file(self, tenant_id: UUID, space_id: UUID, file_id: UUID, **data: Any) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel).where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.id == file_id,
                )
            )
            if row is not None:
                if data.get("if_match") is None:
                    from s3mp.common.api.etag import require_if_match
                    require_if_match(None)
                if row.etag != data.get("if_match"):
                    from s3mp.common.api.etag import check_etag
                    check_etag(row.etag or "", data.get("if_match"))
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
                row.status = "deleting"
                row.deletion_principal_id = data.get("actor_principal_id")
                row.deletion_authorization_version = data.get("authorization_version")
                row.deletion_authorization_evidence = data.get("authorization_evidence")

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
                select(FileObjectModel).where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.id == file_id,
                    FileObjectModel.status == "deleting",
                ).with_for_update()
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
                    seconds=min(300, 2 ** row.deletion_attempt_count)
                )

    async def finalize_file_delete(self, tenant_id: UUID, file_id: UUID) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel).where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.id == file_id,
                    FileObjectModel.status == "deleting",
                ).with_for_update()
            )
            if row is not None:
                await session.delete(row)

    async def create_operation(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            model = FileOperationModel(
                tenant_id=tenant_id,
                principal_id=UUID(data.get("principal_id", str(uuid4()))),
                operation_type=data["operation_type"],
                source_key=data.get("source_key"),
                destination_key=data.get("destination_key"),
                keys=data.get("keys", []),
                idempotency_key=data.get("idempotency_key", str(uuid4())),
                status="pending",
                storage_space_id=space_id,
                authorization_version=int(data.get("authorization_version", 1)),
                authorization_evidence=data.get("authorization_evidence", {}),
            )
            session.add(model)
            await session.flush()
            return _op_dict(model)

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
                    or_(FileOperationModel.next_retry_at.is_(None), FileOperationModel.next_retry_at <= now),
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
                .where(FileOperationModel.tenant_id == tenant_id, FileOperationModel.id == operation_id)
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
                        seconds=min(300, 2 ** row.attempt_count)
                    )
            else:
                row.next_retry_at = None
            row.status, row.failure_reason = status, reason
            row.lease_owner, row.lease_expires_at = None, None
            if status in {"succeeded", "failed", "partial_failure", "cancelled"}:
                row.completed_at = datetime.now(UTC)

    async def get_operation(self, tenant_id: UUID, op_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(FileOperationModel).where(
                    FileOperationModel.tenant_id == tenant_id,
                    FileOperationModel.id == op_id,
                )
            )
            return _op_dict(row) if row else None

    async def operation_metrics(self) -> dict[str, int]:
        now = datetime.now(UTC)
        async with self._sf() as session:
            rows = await session.execute(
                select(FileOperationModel.status, func.count())
                .group_by(FileOperationModel.status)
            )
            metrics = {f"status_{status}": int(count) for status, count in rows}
            metrics["stale_leases"] = int(await session.scalar(
                select(func.count()).select_from(FileOperationModel).where(
                    FileOperationModel.status == "running",
                    FileOperationModel.lease_expires_at < now,
                )
            ) or 0)
            metrics["backlog"] = sum(
                metrics.get(f"status_{status}", 0) for status in ("pending", "retry_wait", "running")
            )
            return metrics

    # ── Uploads ────────────────────────────────────────────────────────────

    async def create_upload(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            model = UploadSessionModel(
                tenant_id=tenant_id,
                principal_id=UUID(data["principal_id"]),
                storage_space_id=space_id,
                object_key=data["object_key"],
                declared_length=data["content_length"],
                content_type=data["content_type"],
                checksum=data.get("checksum"),
                expires_at=datetime.now(UTC).replace(hour=23, minute=59, second=59),
                status="pending",
            )
            session.add(model)
            await session.flush()
            return _upload_dict(model)

    async def get_upload(self, tenant_id: UUID, upload_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(UploadSessionModel).where(
                    UploadSessionModel.tenant_id == tenant_id,
                    UploadSessionModel.id == upload_id,
                )
            )
            return _upload_dict(row) if row else None

    async def expire_upload(self, tenant_id: UUID, upload_id: UUID) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(UploadSessionModel).where(
                    UploadSessionModel.tenant_id == tenant_id,
                    UploadSessionModel.id == upload_id,
                ).with_for_update()
            )
            if row is not None and row.status == "pending":
                row.status = "expired"

    async def complete_upload(
        self, tenant_id: UUID, upload_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(UploadSessionModel).where(
                    UploadSessionModel.tenant_id == tenant_id,
                    UploadSessionModel.id == upload_id,
                ).with_for_update()
            )
            if row is None:
                raise ValueError("upload not found")
            row.status = "completed"
            row.completed_at = datetime.now(UTC)
            # Create file_object record so the file is visible in list_files
            file_obj = FileObjectModel(
                tenant_id=tenant_id,
                storage_space_id=row.storage_space_id,
                object_key=row.object_key,
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
            model = MultipartSessionModel(
                tenant_id=tenant_id,
                principal_id=UUID(data["principal_id"]),
                storage_space_id=space_id,
                object_key=data["object_key"],
                declared_length=data["content_length"],
                content_type=data["content_type"],
                quota_reservation_id=uuid4(),
                expires_at=datetime.now(UTC).replace(hour=23, minute=59, second=59),
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
                select(MultipartSessionModel).where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == multipart_id,
                ).with_for_update()
            )
            if row is None:
                raise ValueError("multipart not found")
            row.provider_upload_id = provider_upload_id
            await session.flush()
            return _mp_dict(row)

    async def get_multipart(self, tenant_id: UUID, mp_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(MultipartSessionModel).where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == mp_id,
                )
            )
            return _mp_dict(row) if row else None

    async def expire_multipart(self, tenant_id: UUID, mp_id: UUID) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartSessionModel).where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == mp_id,
                ).with_for_update()
            )
            if row is not None and row.status == "pending":
                row.status = "expired"

    async def abort_multipart(self, tenant_id: UUID, mp_id: UUID, *, idempotency_key: str | None = None) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartSessionModel).where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == mp_id,
                ).with_for_update()
            )
            if row is not None:
                row.status = "aborted"
                await session.flush()

    async def list_multipart_parts(self, tenant_id: UUID, mp_id: UUID) -> list[dict[str, Any]]:
        async with self._sf() as session:
            rows = await session.scalars(
                select(MultipartPartModel).where(
                    MultipartPartModel.tenant_id == tenant_id,
                    MultipartPartModel.multipart_session_id == mp_id,
                ).order_by(MultipartPartModel.part_number)
            )
            return [_part_dict(r) for r in rows]

    async def create_multipart_part(
        self, tenant_id: UUID, mp_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            model = MultipartPartModel(
                tenant_id=tenant_id,
                multipart_session_id=mp_id,
                part_number=data["part_number"],
                etag="pending",
                content_length=0,
            )
            session.add(model)
            await session.flush()
            return _part_dict(model)

    async def confirm_multipart_part(
        self, tenant_id: UUID, mp_id: UUID, part_number: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartPartModel).where(
                    MultipartPartModel.tenant_id == tenant_id,
                    MultipartPartModel.multipart_session_id == mp_id,
                    MultipartPartModel.part_number == part_number,
                ).with_for_update()
            )
            if row is None:
                raise ValueError("part not found")
            row.etag = data["etag"]
            row.content_length = data["content_length"]
            await session.flush()
            return _part_dict(row)

    async def complete_multipart(
        self, tenant_id: UUID, mp_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartSessionModel).where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == mp_id,
                ).with_for_update()
            )
            if row is None:
                raise ValueError("multipart not found")
            row.status = "completed"
            await session.flush()
            return _mp_dict(row)


def _file_dict(m: FileObjectModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "storage_space_id": str(m.storage_space_id), "object_key": m.object_key,
        "content_length": m.content_length, "content_type": m.content_type,
        "etag": m.etag, "checksum": m.checksum,
        "status": m.status,
        "deletion_attempt_count": m.deletion_attempt_count,
        "deletion_principal_id": str(m.deletion_principal_id) if m.deletion_principal_id else None,
        "deletion_authorization_version": m.deletion_authorization_version,
        "deletion_authorization_evidence": m.deletion_authorization_evidence,
        "created_at": m.created_at.isoformat(),
    }


def _upload_dict(m: UploadSessionModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "principal_id": str(m.principal_id), "object_key": m.object_key,
        "storage_space_id": str(m.storage_space_id),
        "content_length": m.declared_length, "content_type": m.content_type,
        "status": m.status, "checksum": m.checksum,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
    }


def _mp_dict(m: MultipartSessionModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "principal_id": str(m.principal_id), "object_key": m.object_key,
        "storage_space_id": str(m.storage_space_id),
        "content_length": m.declared_length, "content_type": m.content_type,
        "status": m.status, "provider_upload_id": m.provider_upload_id,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
    }


def _part_dict(m: MultipartPartModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "part_number": m.part_number,
        "etag": m.etag, "content_length": m.content_length,
    }


def _op_dict(m: FileOperationModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "principal_id": str(m.principal_id),
        "operation_type": m.operation_type, "status": m.status,
        "source_key": m.source_key, "destination_key": m.destination_key,
        "keys": list(m.keys or ()),
        "idempotency_key": m.idempotency_key,
        "failure_reason": m.failure_reason,
        "storage_space_id": str(m.storage_space_id) if m.storage_space_id else None,
        "authorization_version": m.authorization_version,
        "authorization_evidence": m.authorization_evidence or {},
        "attempt_count": m.attempt_count,
        "lease_owner": m.lease_owner,
        "lease_expires_at": m.lease_expires_at.isoformat() if m.lease_expires_at else None,
        "next_retry_at": m.next_retry_at.isoformat() if m.next_retry_at else None,
        "completed_at": m.completed_at.isoformat() if m.completed_at else None,
        "created_at": m.created_at.isoformat(),
    }
