"""Ingestion state machine: initiate → upload → verify → commit → available."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class IngestionStatus(StrEnum):
    INITIATED = "initiated"
    UPLOADING = "uploading"
    VERIFICATION_PENDING = "verification_pending"
    VERIFIED = "verified"
    COMMITTED = "committed"
    AVAILABLE = "available"
    FAILED = "failed"
    EXPIRED = "expired"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class IngestionEventType(StrEnum):
    CREATED = "created"
    UPLOAD_STARTED = "upload_started"
    UPLOAD_COMPLETED = "upload_completed"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"
    COMMITTED = "committed"
    MARKED_AVAILABLE = "marked_available"
    RECONCILIATION_STARTED = "reconciliation_started"
    RECONCILIATION_SUCCEEDED = "reconciliation_succeeded"
    RECONCILIATION_FAILED = "reconciliation_failed"
    EXPIRED = "expired"
    FAILED_PERMANENTLY = "failed_permanently"


VALID_TRANSITIONS: dict[IngestionStatus, set[IngestionStatus]] = {
    IngestionStatus.INITIATED: {
        IngestionStatus.UPLOADING,
        IngestionStatus.VERIFIED,
        IngestionStatus.FAILED,
        IngestionStatus.RECONCILIATION_REQUIRED,
        IngestionStatus.EXPIRED,
    },
    IngestionStatus.UPLOADING: {
        IngestionStatus.VERIFICATION_PENDING,
        IngestionStatus.FAILED,
        IngestionStatus.EXPIRED,
    },
    IngestionStatus.VERIFICATION_PENDING: {
        IngestionStatus.VERIFIED,
        IngestionStatus.FAILED,
        IngestionStatus.EXPIRED,
    },
    IngestionStatus.VERIFIED: {
        IngestionStatus.COMMITTED,
        IngestionStatus.FAILED,
        IngestionStatus.RECONCILIATION_REQUIRED,
    },
    IngestionStatus.COMMITTED: {IngestionStatus.AVAILABLE, IngestionStatus.RECONCILIATION_REQUIRED},
    IngestionStatus.AVAILABLE: set(),
    IngestionStatus.FAILED: {IngestionStatus.RECONCILIATION_REQUIRED},
    IngestionStatus.EXPIRED: set(),
    IngestionStatus.RECONCILIATION_REQUIRED: {
        IngestionStatus.VERIFIED,
        IngestionStatus.COMMITTED,
        IngestionStatus.FAILED,
    },
}


@dataclass(frozen=True, slots=True)
class IngestionRecord:
    id: UUID
    tenant_id: UUID
    creator_principal_id: UUID
    acting_principal_id: UUID
    storage_space_id: UUID
    bucket: str
    relative_key: str
    physical_key: str
    authorization_evidence: dict[str, Any]
    authorization_version: int
    status: IngestionStatus = IngestionStatus.INITIATED
    upload_session_id: UUID | None = None
    multipart_session_id: UUID | None = None
    file_object_id: UUID | None = None
    provider_etag: str | None = None
    provider_version_id: str | None = None
    actual_size: int | None = None
    actual_content_type: str | None = None
    checksum: str | None = None
    request_id: str | None = None
    idempotency_key: str | None = None
    idempotency_fingerprint: str | None = None
    committed_at: datetime | None = None
    created_at: datetime = datetime.now(UTC)

    def transition(self, target: IngestionStatus) -> "IngestionRecord":
        allowed = VALID_TRANSITIONS.get(self.status, set())
        if target not in allowed:
            raise ValueError(f"Invalid ingestion transition: {self.status} → {target}")
        updates: dict[str, Any] = {"status": target}
        if target is IngestionStatus.COMMITTED:
            updates["committed_at"] = datetime.now(UTC)
        return replace(self, **updates)


@dataclass(frozen=True, slots=True)
class IngestionEvent:
    id: UUID
    ingestion_record_id: UUID
    tenant_id: UUID
    event_type: IngestionEventType
    details: dict[str, Any]
    occurred_at: datetime = datetime.now(UTC)
