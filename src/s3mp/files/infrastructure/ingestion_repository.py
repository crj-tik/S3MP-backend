"""Ingestion repository: begin-or-replay, provider-result, commit-verified, fail-or-quarantine, append-event.

Design: see openspec/changes/close-file-security-and-ingestion-gaps/design.md §4.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.common.errors import ApiError
from s3mp.files.domain.ingestion import (
    VALID_TRANSITIONS,
    IngestionEventType,
    IngestionStatus,
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
from s3mp.files.infrastructure.repositories import _mp_dict, _upload_dict
from s3mp.governance.infrastructure.models import QuotaModel, QuotaReservationModel


class SqlAlchemyIngestionStore:
    """Durable ingestion lifecycle backed by PostgreSQL.

    Every mutation is scoped to (tenant_id, ingestion_id) and validates
    the state-machine transition before persisting.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create_upload_intent(
        self, tenant_id: UUID, session_data: dict[str, Any], ingestion_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomically create or replay an upload session and its ingestion intent."""
        async with self._sf.begin() as session:
            existing = await _find_replay_or_conflict(session, tenant_id, ingestion_data)
            if existing is not None:
                if existing.upload_session_id is None:
                    raise ApiError("invalid_transition", "Ingestion does not reference an upload", 409)
                upload = await session.get(UploadSessionModel, existing.upload_session_id)
                if upload is None:
                    raise ApiError("invalid_transition", "Ingestion upload is unavailable", 409)
                result = _upload_dict(upload)
                result.update({"ingestion_id": str(existing.id), "replayed": True})
                return result

            quota_reservation_id = await _reserve_quota(
                session, tenant_id, UUID(session_data["storage_space_id"]), session_data["content_length"]
            )
            upload = UploadSessionModel(
                tenant_id=tenant_id,
                principal_id=UUID(session_data["principal_id"]),
                storage_space_id=UUID(session_data["storage_space_id"]),
                object_key=session_data["object_key"],
                declared_length=session_data["content_length"],
                content_type=session_data["content_type"],
                checksum=session_data.get("checksum"),
                expires_at=session_data["expires_at"],
                status="pending",
            )
            session.add(upload)
            await session.flush()
            ingestion_data = {
                **ingestion_data,
                "upload_session_id": str(upload.id),
                "quota_reservation_id": str(quota_reservation_id) if quota_reservation_id else None,
            }
            record = _build_ingestion_model(tenant_id, ingestion_data)
            session.add(record)
            await session.flush()
            _append_created_event(session, record)
            await session.flush()
            result = _upload_dict(upload)
            result.update({"ingestion_id": str(record.id), "replayed": False})
            return result

    async def create_multipart_intent(
        self, tenant_id: UUID, session_data: dict[str, Any], ingestion_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomically create or replay a multipart session and ingestion intent."""
        async with self._sf.begin() as session:
            existing = await _find_replay_or_conflict(session, tenant_id, ingestion_data)
            if existing is not None:
                if existing.multipart_session_id is None:
                    raise ApiError("invalid_transition", "Ingestion does not reference multipart", 409)
                multipart = await session.get(MultipartSessionModel, existing.multipart_session_id)
                if multipart is None:
                    raise ApiError("invalid_transition", "Ingestion multipart is unavailable", 409)
                result = _mp_dict(multipart)
                result.update({"ingestion_id": str(existing.id), "replayed": True})
                return result

            quota_reservation_id = await _reserve_quota(
                session, tenant_id, UUID(session_data["storage_space_id"]), session_data["content_length"]
            )
            multipart = MultipartSessionModel(
                tenant_id=tenant_id,
                principal_id=UUID(session_data["principal_id"]),
                storage_space_id=UUID(session_data["storage_space_id"]),
                object_key=session_data["object_key"],
                declared_length=session_data["content_length"],
                content_type=session_data["content_type"],
                quota_reservation_id=quota_reservation_id or uuid4(),
                expires_at=session_data["expires_at"],
                status="pending",
            )
            session.add(multipart)
            await session.flush()
            ingestion_data = {
                **ingestion_data,
                "multipart_session_id": str(multipart.id),
                "quota_reservation_id": str(quota_reservation_id) if quota_reservation_id else None,
            }
            record = _build_ingestion_model(tenant_id, ingestion_data)
            session.add(record)
            await session.flush()
            _append_created_event(session, record)
            await session.flush()
            result = _mp_dict(multipart)
            result.update({"ingestion_id": str(record.id), "replayed": False})
            return result

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
        async with self._sf.begin() as session:
            existing = await _find_replay_or_conflict(session, tenant_id, data)
            if existing is not None:
                return _ingestion_dict(existing)

            # 3. Insert
            model = _build_ingestion_model(tenant_id, data)
            session.add(model)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                raise ApiError(
                    "idempotency_key_reused",
                    "A conflicting request was processed concurrently",
                    status_code=409,
                ) from None
            _append_created_event(session, model)
            await session.flush()
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

    async def get_for_session(
        self,
        tenant_id: UUID,
        *,
        upload_session_id: UUID | None = None,
        multipart_session_id: UUID | None = None,
    ) -> dict[str, Any] | None:
        """Return the original durable intent linked to exactly one session."""
        if (upload_session_id is None) == (multipart_session_id is None):
            raise ValueError("exactly one session id is required")
        column = (
            FileIngestionRecordModel.upload_session_id
            if upload_session_id is not None
            else FileIngestionRecordModel.multipart_session_id
        )
        session_id = upload_session_id or multipart_session_id
        async with self._sf() as session:
            row = await session.scalar(
                select(FileIngestionRecordModel)
                .where(
                    FileIngestionRecordModel.tenant_id == tenant_id,
                    column == session_id,
                )
                .order_by(FileIngestionRecordModel.created_at.desc())
            )
            return _ingestion_dict(row) if row else None

    async def list_pending(
        self, tenant_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        """List records which require provider re-verification or cleanup."""
        pending_statuses = (
            IngestionStatus.INITIATED.value,
            IngestionStatus.VERIFIED.value,
            IngestionStatus.RECONCILIATION_REQUIRED.value,
        )
        async with self._sf() as session:
            stmt = select(FileIngestionRecordModel).where(
                FileIngestionRecordModel.status.in_(pending_statuses)
            )
            if tenant_id is not None:
                stmt = stmt.where(FileIngestionRecordModel.tenant_id == tenant_id)
            rows = await session.scalars(stmt.order_by(FileIngestionRecordModel.created_at))
            return [_ingestion_dict(row) for row in rows]

    async def reconciliation_attempt_count(self, tenant_id: UUID, ingestion_id: UUID) -> int:
        async with self._sf() as session:
            return int(await session.scalar(
                select(func.count()).select_from(FileIngestionEventModel).where(
                    FileIngestionEventModel.tenant_id == tenant_id,
                    FileIngestionEventModel.ingestion_record_id == ingestion_id,
                    FileIngestionEventModel.event_type == IngestionEventType.RECONCILIATION_STARTED.value,
                )
            ) or 0)

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
            if row.status == IngestionStatus.COMMITTED.value:
                return await _committed_result(session, row)
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
            await _settle_quota_reservation(session, tenant_id, row)

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
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=row.acting_principal_id,
                    action="file.ingestion.committed",
                    resource_type="file_object",
                    resource_id=str(file_obj.id),
                    details={
                        "request_id": row.request_id,
                        "storage_space_id": str(row.storage_space_id),
                        "object_key_fingerprint": hashlib.sha256(
                            row.physical_key.encode("utf-8")
                        ).hexdigest(),
                        "ingestion_id": str(row.id),
                    },
                )
            )
            await session.flush()

            return await _committed_result(session, row)

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
            if row.status == status.value and status is IngestionStatus.RECONCILIATION_REQUIRED:
                session.add(
                    FileIngestionEventModel(
                        ingestion_record_id=ingestion_id,
                        tenant_id=tenant_id,
                        event_type=IngestionEventType.RECONCILIATION_STARTED.value,
                        details={"reason": reason, **(details or {})},
                    )
                )
                return _ingestion_dict(row)
            _validate_transition(row, status)

            row.status = status.value
            if status is IngestionStatus.FAILED:
                await _release_quota_reservation(session, tenant_id, row)

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

    async def expire(self, tenant_id: UUID, ingestion_id: UUID) -> dict[str, Any]:
        """Expire a pending intent and release any unconsumed reservation."""
        async with self._sf.begin() as session:
            row = await _lock_ingestion_row(session, tenant_id, ingestion_id)
            if row.status == IngestionStatus.EXPIRED.value:
                return _ingestion_dict(row)
            _validate_transition(row, IngestionStatus.EXPIRED)
            row.status = IngestionStatus.EXPIRED.value
            await _release_quota_reservation(session, tenant_id, row)
            session.add(
                FileIngestionEventModel(
                    ingestion_record_id=ingestion_id,
                    tenant_id=tenant_id,
                    event_type=IngestionEventType.EXPIRED.value,
                    details={"reason": "session_expired"},
                )
            )
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


async def _find_replay_or_conflict(
    session: AsyncSession, tenant_id: UUID, data: dict[str, Any]
) -> FileIngestionRecordModel | None:
    """Return a matching idempotent intent or reject conflicting key reuse."""
    fingerprint = data.get("idempotency_fingerprint")
    idempotency_key = data.get("idempotency_key")
    if fingerprint:
        existing = await session.scalar(
            select(FileIngestionRecordModel).where(
                FileIngestionRecordModel.tenant_id == tenant_id,
                FileIngestionRecordModel.idempotency_fingerprint == fingerprint,
            )
        )
        if existing is not None:
            return existing
    if idempotency_key:
        conflicting = await session.scalar(
            select(FileIngestionRecordModel).where(
                FileIngestionRecordModel.tenant_id == tenant_id,
                FileIngestionRecordModel.idempotency_key == idempotency_key,
            )
        )
        if conflicting is not None:
            raise ApiError(
                "idempotency_key_reused",
                "Idempotency-Key was already used with different request semantics",
                status_code=409,
            )
    return None


def _append_created_event(session: AsyncSession, record: FileIngestionRecordModel) -> None:
    """Write immutable creation evidence in the same transaction as the intent."""
    session.add(
        FileIngestionEventModel(
            ingestion_record_id=record.id,
            tenant_id=record.tenant_id,
            event_type=IngestionEventType.CREATED.value,
            details={
                "request_id": record.request_id,
                "idempotency_key": record.idempotency_key,
                "authorization_version": record.authorization_version,
            },
        )
    )


async def _reserve_quota(
    session: AsyncSession, tenant_id: UUID, storage_space_id: UUID, requested_bytes: int
) -> UUID | None:
    """Reserve configured space quota under the caller's transaction lock."""
    quota = await session.scalar(
        select(QuotaModel)
        .where(
            QuotaModel.tenant_id == tenant_id,
            QuotaModel.storage_space_id == storage_space_id,
        )
        .with_for_update()
    )
    if quota is None:
        return None
    if requested_bytes < 0 or quota.used_bytes + quota.reserved_bytes + requested_bytes > quota.limit_bytes:
        raise ApiError("quota_exceeded", "Quota capacity exceeded", status_code=409)
    reservation = QuotaReservationModel(
        tenant_id=tenant_id,
        quota_id=quota.id,
        requested_bytes=requested_bytes,
        status="reserved",
    )
    quota.reserved_bytes += requested_bytes
    session.add(reservation)
    await session.flush()
    return reservation.id


async def _settle_quota_reservation(
    session: AsyncSession, tenant_id: UUID, row: FileIngestionRecordModel
) -> None:
    if row.quota_reservation_id is None:
        return
    reservation = await session.scalar(
        select(QuotaReservationModel)
        .where(
            QuotaReservationModel.tenant_id == tenant_id,
            QuotaReservationModel.id == row.quota_reservation_id,
        )
        .with_for_update()
    )
    if reservation is None or reservation.status != "reserved":
        return
    quota = await session.scalar(
        select(QuotaModel)
        .where(QuotaModel.tenant_id == tenant_id, QuotaModel.id == reservation.quota_id)
        .with_for_update()
    )
    if quota is None:
        raise ApiError("quota_exceeded", "Quota is unavailable", status_code=409)
    actual_size = row.actual_size or 0
    if quota.used_bytes + actual_size > quota.limit_bytes:
        raise ApiError("quota_exceeded", "Verified object exceeds quota", status_code=409)
    quota.reserved_bytes -= reservation.requested_bytes
    quota.used_bytes += actual_size
    reservation.actual_bytes = actual_size
    reservation.status = "settled"
    reservation.settled_at = datetime.now(UTC)


async def _release_quota_reservation(
    session: AsyncSession, tenant_id: UUID, row: FileIngestionRecordModel
) -> None:
    if row.quota_reservation_id is None:
        return
    reservation = await session.scalar(
        select(QuotaReservationModel)
        .where(
            QuotaReservationModel.tenant_id == tenant_id,
            QuotaReservationModel.id == row.quota_reservation_id,
        )
        .with_for_update()
    )
    if reservation is None or reservation.status != "reserved":
        return
    quota = await session.scalar(
        select(QuotaModel)
        .where(QuotaModel.tenant_id == tenant_id, QuotaModel.id == reservation.quota_id)
        .with_for_update()
    )
    if quota is not None:
        quota.reserved_bytes -= reservation.requested_bytes
    reservation.status = "released"
    reservation.settled_at = datetime.now(UTC)


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


async def _committed_result(
    session: AsyncSession, row: FileIngestionRecordModel
) -> dict[str, Any]:
    result = _ingestion_dict(row)
    if row.file_object_id is not None:
        file_obj = await session.get(FileObjectModel, row.file_object_id)
        if file_obj is not None:
            result["file_object"] = _file_dict(file_obj)
    return result


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
        quota_reservation_id=(
            UUID(data["quota_reservation_id"])
            if data.get("quota_reservation_id")
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
        "quota_reservation_id": str(m.quota_reservation_id) if m.quota_reservation_id else None,
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
