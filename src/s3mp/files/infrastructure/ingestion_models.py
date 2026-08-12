"""SQLAlchemy models for file_ingestion_record and file_ingestion_event."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from s3mp.common.database import Base


class FileIngestionRecordModel(Base):
    __tablename__ = "file_ingestion_record"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "idempotency_fingerprint"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        # Terminal provenance is retained: session/file references may be
        # removed independently, but tenant scope is never nulled.
        ForeignKeyConstraint(["upload_session_id"], ["upload_session.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["multipart_session_id"], ["multipart_session.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["quota_reservation_id"], ["quota_reservation.id"], ondelete="SET NULL"),
        ForeignKeyConstraint(["file_object_id"], ["file_object.id"], ondelete="SET NULL"),
        Index("ix_ingestion_tenant_status", "tenant_id", "status"),
        Index("ix_ingestion_tenant_session", "tenant_id", "upload_session_id"),
        Index("ix_ingestion_tenant_multipart_session", "tenant_id", "multipart_session_id"),
        Index("ix_ingestion_tenant_quota_reservation", "tenant_id", "quota_reservation_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    upload_session_id: Mapped[UUID | None] = mapped_column()
    multipart_session_id: Mapped[UUID | None] = mapped_column()
    quota_reservation_id: Mapped[UUID | None] = mapped_column()
    file_object_id: Mapped[UUID | None] = mapped_column()
    creator_principal_id: Mapped[UUID] = mapped_column(nullable=False)
    acting_principal_id: Mapped[UUID] = mapped_column(nullable=False)
    storage_space_id: Mapped[UUID] = mapped_column(nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    relative_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    physical_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    provider_etag: Mapped[str | None] = mapped_column(String(512))
    provider_version_id: Mapped[str | None] = mapped_column(String(512))
    actual_size: Mapped[int | None] = mapped_column(Integer())
    actual_content_type: Mapped[str | None] = mapped_column(String(255))
    checksum: Mapped[str | None] = mapped_column(String(512))
    authorization_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    authorization_version: Mapped[int] = mapped_column(nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="initiated")
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FileIngestionEventModel(Base):
    __tablename__ = "file_ingestion_event"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "ingestion_record_id"],
            ["file_ingestion_record.tenant_id", "file_ingestion_record.id"],
            ondelete="CASCADE",
        ),
        Index("ix_ingestion_event_record", "ingestion_record_id", "occurred_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ingestion_record_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
