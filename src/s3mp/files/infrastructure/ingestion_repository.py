"""Ingestion repository: begin-or-replay, provider-result, commit-verified, fail-or-quarantine, append-event.

Design: see openspec/changes/close-file-security-and-ingestion-gaps/design.md §4.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.common.errors import ApiError
from s3mp.files.domain.ingestion import (
    IngestionEventType,
    IngestionStatus,
    VALID_TRANSITIONS,
)
from s3mp.files.infrastructure.ingestion_models import (
    FileIngestionEventModel,
    FileIngestionRecordModel,
)
from s3mp.files.infrastructure.models import (
    FileObjectModel,
    MultipartSessionModel,
    UploadSessionModel,
)


class SqlAlchemyIngestionStore:
    """Durable ingestion lifecycle backed by PostgreSQL.

    Every mutation is scoped to (tenant_id, ingestion_id) and validates
    the state-machine transition before persisting.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def begin_or_replay(
        self, tenant_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomically insert or retrieve an ingestion record by idempotency fingerprint.

        - No fingerprint        → create a new record unconditionally.
        - Fingerprint match     → replay the existing record (idempotent retry).
        - Same idempotency_key,
          different fingerprint → reject with 409 (client reused key with different payload).
        """
        fingerprint: str | None = data.get("idempotency_fingerprint")
        idempotency_key: str | None = data.get("idempotency_key")

        async with self._sf.begin() as session:
            # 1. Replay: fingerprint already seen → return the existing record
            if fingerprint:
                existing = await session.scalar(
                    select(FileIngestionRecordModel).where(
                        FileIngestionRecordModel.tenant_id == tenant_id,
                        FileIngestionRecordModel.idempotency_fingerprint == fingerprint,
                    )
                )
                if existing is not None:
                    return _ingestion_dict(existing)

            # 2. Conflict detection: same key, different payload
            if idempotency_key:
                conflict = await session.scalar(
                    select(FileIngestionRecordModel).where(
                        FileIngestionRecordModel.tenant_id == tenant_id,
                        FileIngestionRecordModel.idempotency_key == idempotency_key,
                    )
                )
                if conflict is not None and conflict.idempotency_fingerprint != fingerprint:
                    raise ApiError(
                        "idempotency_conflict",
                        "A different request with the same idempotency key was already processed",
                        status_code=409,
                    )

            # 3. Insert
            model = _build_ingestion_model(tenant_id, data)
            session.add(model)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                raise ApiError(
                    "idempotency_conflict",
                    "A conflicting request was processed concurrently",
                    status_code=409,
                ) from None
            return _ingestion_dict(model)

    async def get_record(
        self, tenant_id: UUID, ingestion_id: UUID
    ) -> dict[str, Any] | None:
        """Retrieve an ingestion record by id (tenant-scoped)."""
        async with self._sf() as session:
            row = await session.scalar(
                select(FileIngestionRecordModel).where(
                    FileIngestionRecordModel.tenant_id == tenant_id,
                    FileIngestionRecordModel.id == ingestion_id,
                )
            )
            return _ingestion_dict(row) if row else None

    # ── Provider result ──────────────────────────────────────────────────────

    async def record_provider_result(
        self,
        tenant_id: UUID,
        ingestion_id: UUID,
        *,
        provider_etag: str | None = None,
        provider_version_id: str | None = None,
        actual_size: int | None = None,
        actual_content_type: str | None = None,
        checksum: str | None = None,
    ) -> dict[str, Any]:
        """Persist provider metadata and transition to VERIFIED.

        Appends a VERIFICATION_PASSED event.  Caller must have already
        confirmed the object exists in the provider (HeadObject).
        """
        async with self._sf.begin() as session:
            row = await _lock_ingestion_row(session, tenant_id, ingestion_id)
            _validate_transition(row, IngestionStatus.VERIFIED)

            row.provider_etag = provider_etag
            row.provider_version_id = provider_version_id
            row.actual_size = actual_size
            row.actual_content_type = actual_content_type
            row.checksum = checksum
            row.status = IngestionStatus.VERIFIED.value

            event = FileIngestionEventModel(
                ingestion_record_id=ingestion_id,
                tenant_id=tenant_id,
                event_type=IngestionEventType.VERIFICATION_PASSED.value,
                details={
                    "provider_etag": provider_etag,
                    "provider_version_id": provider_version_id,
                    "actual_size": actual_size,
                    "actual_content_type": actual_content_type,
                    "checksum": checksum,
                },
            )
            session.add(event)
            await session.flush()
            return _ingestion_dict(row)

    # ── Commit ───────────────────────────────────────────────────────────────

    async def commit_verified_file(
        self, tenant_id: UUID, ingestion_id: UUID
    ) -> dict[str, Any]:
        """Single-transaction commit: transition ingestion → COMMITTED,
        create FileObject, settle upload/multipart session, append event.

        Returns the ingestion dict with an extra ``file_object`` key.
        """
        async with self._sf.begin() as session:
            row = await _lock_ingestion_row(session, tenant_id, ingestion_id)
            _validate_transition(row, IngestionStatus.COMMITTED)

            # Create the file object so it becomes visible in list_files
            file_obj = FileObjectModel(
                tenant_id=tenant_id,
                storage_space_id=row.storage_space_id,
                object_key=row.physical_key,
                content_length=row.actual_size or 0,
                content_type=row.actual_content_type or "application/octet-stream",
                etag=row.provider_etag,
                checksum=row.checksum,
            )
            session.add(file_obj)
            await session.flush()

            # Update ingestion row
            row.status = IngestionStatus.COMMITTED.value
            row.file_object_id = file_obj.id
            row.committed_at = datetime.now(UTC)

            # Settle the linked upload session
            if row.upload_session_id is not None:
                upload = await session.scalar(
                    select(UploadSessionModel)
                    .where(
                        UploadSessionModel.tenant_id == tenant_id,
                        UploadSessionModel.id == row.upload_session_id,
                    )
                    .with_for_update()
                )
                if upload is not None:
                    upload.status = "completed"
                    upload.completed_at = datetime.now(UTC)

            # Settle the linked multipart session
            if row.multipart_session_id is not None:
                mp = await session.scalar(
                    select(MultipartSessionModel)
                    .where(
                        MultipartSessionModel.tenant_id == tenant_id,
                        MultipartSessionModel.id == row.multipart_session_id,
                    )
                    .with_for_update()
                )
                if mp is not None:
                    mp.status = "completed"

            # Append COMMITTED event
            event = FileIngestionEventModel(
                ingestion_record_id=ingestion_id,
                tenant_id=tenant_id,
                event_type=IngestionEventType.COMMITTED.value,
                details={
                    "file_object_id": str(file_obj.id),
                    "committed_at": datetime.now(UTC).isoformat(),
                },
            )
            session.add(event)
            await session.flush()

            result = _ingestion_dict(row)
            result["file_object"] = _file_dict(file_obj)
            return result

    # ── Terminal states ──────────────────────────────────────────────────────

    async def fail_or_quarantine(
        self,
        tenant_id: UUID,
        ingestion_id: UUID,
        status: IngestionStatus,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Transition to FAILED or RECONCILIATION_REQUIRED; append a terminal event.

        Physical-key details are never embedded in event details.
        """
        if status not in {IngestionStatus.FAILED, IngestionStatus.RECONCILIATION_REQUIRED}:
            raise ValueError("status must be FAILED or RECONCILIATION_REQUIRED")

        async with self._sf.begin() as session:
            row = await _lock_ingestion_row(session, tenant_id, ingestion_id)
            _validate_transition(row, status)

            row.status = status.value

            event_type = (
                IngestionEventType.FAILED_PERMANENTLY
                if status == IngestionStatus.FAILED
                else IngestionEventType.RECONCILIATION_STARTED
            )

            event_details: dict[str, Any] = {"reason": reason}
            if details:
                event_details.update(details)

            event = FileIngestionEventModel(
                ingestion_record_id=ingestion_id,
                tenant_id=tenant_id,
                event_type=event_type.value,
                details=event_details,
            )
            session.add(event)
            await session.flush()
            return _ingestion_dict(row)

    # ── Events ───────────────────────────────────────────────────────────────

    async def append_event(
        self,
        tenant_id: UUID,
        ingestion_id: UUID,
        event_type: IngestionEventType,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        """Append an ingestion event (append-only)."""
        async with self._sf.begin() as session:
            event = FileIngestionEventModel(
                ingestion_record_id=ingestion_id,
                tenant_id=tenant_id,
                event_type=event_type.value,
                details=details,
            )
            session.add(event)
            await session.flush()
            return _event_dict(event)

    async def list_events(
        self, tenant_id: UUID, ingestion_id: UUID
    ) -> list[dict[str, Any]]:
        """List all events for an ingestion record, ordered by time."""
        async with self._sf() as session:
            rows = await session.scalars(
                select(FileIngestionEventModel)
                .where(
                    FileIngestionEventModel.tenant_id == tenant_id,
                    FileIngestionEventModel.ingestion_record_id == ingestion_id,
                )
                .order_by(FileIngestionEventModel.occurred_at)
            )
            return [_event_dict(r) for r in rows]


# ── Internal helpers ─────────────────────────────────────────────────────────


async def _lock_ingestion_row(
    session: AsyncSession, tenant_id: UUID, ingestion_id: UUID
) -> FileIngestionRecordModel:
    """Select … FOR UPDATE and raise 404 if missing."""
    row = await session.scalar(
        select(FileIngestionRecordModel)
        .where(
            FileIngestionRecordModel.tenant_id == tenant_id,
            FileIngestionRecordModel.id == ingestion_id,
        )
        .with_for_update()
    )
    if row is None:
        raise ApiError("resource_not_found", "Ingestion record not found", status_code=404)
    return row


def _validate_transition(
    row: FileIngestionRecordModel, target: IngestionStatus
) -> None:
    current = IngestionStatus(row.status)
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ApiError(
            "invalid_transition",
            f"Cannot transition ingestion from {current.value} to {target.value}",
            status_code=409,
        )


def _build_ingestion_model(
    tenant_id: UUID, data: dict[str, Any]
) -> FileIngestionRecordModel:
    return FileIngestionRecordModel(
        tenant_id=tenant_id,
        creator_principal_id=UUID(data["creator_principal_id"]),
        acting_principal_id=UUID(data["acting_principal_id"]),
        storage_space_id=UUID(data["storage_space_id"]),
        bucket=data["bucket"],
        relative_key=data["relative_key"],
        physical_key=data["physical_key"],
        authorization_evidence=data["authorization_evidence"],
        authorization_version=data["authorization_version"],
        request_id=data.get("request_id"),
        idempotency_key=data.get("idempotency_key"),
        idempotency_fingerprint=data.get("idempotency_fingerprint"),
        upload_session_id=(
            UUID(data["upload_session_id"])
            if data.get("upload_session_id")
            else None
        ),
        multipart_session_id=(
            UUID(data["multipart_session_id"])
            if data.get("multipart_session_id")
            else None
        ),
        status="initiated",
    )


# ── Dict serializers ─────────────────────────────────────────────────────────


def _ingestion_dict(m: FileIngestionRecordModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "creator_principal_id": str(m.creator_principal_id),
        "acting_principal_id": str(m.acting_principal_id),
        "storage_space_id": str(m.storage_space_id),
        "bucket": m.bucket,
        "relative_key": m.relative_key,
        "physical_key": m.physical_key,
        "authorization_evidence": m.authorization_evidence,
        "authorization_version": m.authorization_version,
        "status": m.status,
        "upload_session_id": str(m.upload_session_id) if m.upload_session_id else None,
        "multipart_session_id": str(m.multipart_session_id) if m.multipart_session_id else None,
        "file_object_id": str(m.file_object_id) if m.file_object_id else None,
        "provider_etag": m.provider_etag,
        "provider_version_id": m.provider_version_id,
        "actual_size": m.actual_size,
        "actual_content_type": m.actual_content_type,
        "checksum": m.checksum,
        "request_id": m.request_id,
        "idempotency_key": m.idempotency_key,
        "idempotency_fingerprint": m.idempotency_fingerprint,
        "committed_at": m.committed_at.isoformat() if m.committed_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _event_dict(m: FileIngestionEventModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "ingestion_record_id": str(m.ingestion_record_id),
        "tenant_id": str(m.tenant_id),
        "event_type": m.event_type,
        "details": m.details,
        "occurred_at": m.occurred_at.isoformat() if m.occurred_at else None,
    }


def _file_dict(m: FileObjectModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "storage_space_id": str(m.storage_space_id),
        "object_key": m.object_key,
        "content_length": m.content_length,
        "content_type": m.content_type,
        "etag": m.etag,
        "checksum": m.checksum,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }