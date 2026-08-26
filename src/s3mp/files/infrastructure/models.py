"""Tenant-bound persistence for files and incomplete uploads."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from s3mp.common.database import Base


class FileObjectModel(Base):
    __tablename__ = "file_object"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "storage_space_id"],
            ["storage_space.tenant_id", "storage_space.id"],
            ondelete="CASCADE",
        ),
        Index("ix_file_object_tenant_space_key", "tenant_id", "storage_space_id", "object_key"),
        Index(
            "ix_file_object_retention_due",
            "purge_due_at",
            postgresql_where=text("soft_deleted AND purge_due_at IS NOT NULL"),
        ),
        Index(
            "uq_file_object_active_key",
            "tenant_id",
            "storage_space_id",
            "object_key",
            unique=True,
            postgresql_where=text(
                "soft_deleted OR status IN "
                "('available', 'renaming', 'rename_failed', 'deleting', 'delete_failed')"
            ),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    storage_space_id: Mapped[UUID] = mapped_column(nullable=False)
    application_id: Mapped[UUID | None] = mapped_column()
    storage_namespace: Mapped[str | None] = mapped_column(String(512))
    profile_version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Version 0 is reserved for rows that predate tenant-scoped provider keys.
    # The application always supplies version 1 for newly created rows.
    provider_target_version: Mapped[int] = mapped_column(
        nullable=False, default=1, server_default="0"
    )
    content_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    etag: Mapped[str | None] = mapped_column(String(512))
    checksum: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    deletion_attempt_count: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    deletion_next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_failure_reason: Mapped[str | None] = mapped_column(String(128))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_principal_id: Mapped[UUID | None] = mapped_column()
    deletion_actor_application_id: Mapped[UUID | None] = mapped_column()
    deletion_authorization_version: Mapped[int | None] = mapped_column()
    deletion_authorization_evidence: Mapped[dict[str, object] | None] = mapped_column(JSON)
    deletion_idempotency_key: Mapped[str | None] = mapped_column(String(128))
    # A rename tombstone is only historical.  A retained deletion keeps the
    # provider object and reserves its canonical key until physical purge.
    soft_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    purge_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_state: Mapped[str | None] = mapped_column(String(32))
    purge_attempt_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    purge_next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_failure_reason: Mapped[str | None] = mapped_column(String(128))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restore_idempotency_key: Mapped[str | None] = mapped_column(String(128))
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FileRetentionOutboxModel(Base):
    """Durable Redis ZSET synchronisation intent; PostgreSQL stays authoritative."""

    __tablename__ = "file_retention_outbox"
    __table_args__ = (
        UniqueConstraint("tenant_id", "file_id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "file_id"],
            ["file_object.tenant_id", "file_object.id"],
            ondelete="CASCADE",
        ),
        Index("ix_file_retention_outbox_pending", "processed_at", "next_retry_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    file_id: Mapped[UUID] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UploadSessionModel(Base):
    __tablename__ = "upload_session"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "storage_space_id"],
            ["storage_space.tenant_id", "storage_space.id"],
            ondelete="CASCADE",
        ),
        Index("ix_upload_session_tenant_status_expires", "tenant_id", "status", "expires_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    principal_id: Mapped[UUID] = mapped_column(nullable=False)
    membership_id: Mapped[UUID | None] = mapped_column()
    storage_space_id: Mapped[UUID] = mapped_column(nullable=False)
    application_id: Mapped[UUID | None] = mapped_column()
    actor_application_id: Mapped[UUID | None] = mapped_column()
    storage_namespace: Mapped[str | None] = mapped_column(String(512))
    profile_version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    provider_target_version: Mapped[int] = mapped_column(
        nullable=False, default=1, server_default="0"
    )
    declared_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MultipartSessionModel(Base):
    __tablename__ = "multipart_session"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"], ["principal.tenant_id", "principal.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "storage_space_id"], ["storage_space.tenant_id", "storage_space.id"]
        ),
        Index("ix_multipart_session_tenant_status_expires", "tenant_id", "status", "expires_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    principal_id: Mapped[UUID] = mapped_column(nullable=False)
    membership_id: Mapped[UUID | None] = mapped_column()
    storage_space_id: Mapped[UUID] = mapped_column(nullable=False)
    application_id: Mapped[UUID | None] = mapped_column()
    actor_application_id: Mapped[UUID | None] = mapped_column()
    storage_namespace: Mapped[str | None] = mapped_column(String(512))
    profile_version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    provider_target_version: Mapped[int] = mapped_column(
        nullable=False, default=1, server_default="0"
    )
    provider_upload_id: Mapped[str | None] = mapped_column(String(512))
    declared_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    quota_reservation_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MultipartPartModel(Base):
    __tablename__ = "multipart_part"
    __table_args__ = (
        UniqueConstraint("tenant_id", "multipart_session_id", "part_number"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "multipart_session_id"],
            ["multipart_session.tenant_id", "multipart_session.id"],
            ondelete="CASCADE",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    multipart_session_id: Mapped[UUID] = mapped_column(nullable=False)
    part_number: Mapped[int] = mapped_column(Integer, nullable=False)
    etag: Mapped[str] = mapped_column(String(512), nullable=False)
    content_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    content_sha256: Mapped[str | None] = mapped_column(String(64))


class FileOperationModel(Base):
    __tablename__ = "file_operation"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"], ["principal.tenant_id", "principal.id"]
        ),
        Index("ix_file_operation_tenant_status", "tenant_id", "status"),
        Index(
            "uq_file_operation_rename_source_active",
            "tenant_id",
            "source_file_id",
            unique=True,
            postgresql_where=text(
                "operation_type = 'rename' AND "
                "status IN ('pending', 'running', 'retry_wait', 'partial_failure')"
            ),
        ),
        Index(
            "uq_file_operation_rename_idempotency",
            "tenant_id",
            "application_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("operation_type = 'rename'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    principal_id: Mapped[UUID] = mapped_column(nullable=False)
    membership_id: Mapped[UUID | None] = mapped_column()
    operation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_key: Mapped[str | None] = mapped_column(String(1024))
    destination_key: Mapped[str | None] = mapped_column(String(1024))
    source_file_id: Mapped[UUID | None] = mapped_column()
    result_file_id: Mapped[UUID | None] = mapped_column()
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_space_id: Mapped[UUID | None] = mapped_column()
    application_id: Mapped[UUID | None] = mapped_column()
    actor_application_id: Mapped[UUID | None] = mapped_column()
    storage_namespace: Mapped[str | None] = mapped_column(String(512))
    profile_version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    authorization_version: Mapped[int] = mapped_column(
        nullable=False, default=1, server_default="1"
    )
    provider_target_version: Mapped[int] = mapped_column(
        nullable=False, default=1, server_default="0"
    )
    authorization_evidence: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProviderMigrationManifestModel(Base):
    """Durable, operator-reviewed manifest for one legacy provider target."""

    __tablename__ = "provider_migration_manifest"
    __table_args__ = (
        UniqueConstraint("tenant_id", "record_type", "record_id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        Index("ix_provider_migration_manifest_state", "state", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    storage_space_id: Mapped[UUID | None] = mapped_column()
    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    record_id: Mapped[UUID] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_review")
    # Provider locations stay internal to the durable migration workflow. They
    # are never returned by API DTOs or printed by migration commands.
    source_bucket: Mapped[str | None] = mapped_column(String(255))
    source_key: Mapped[str | None] = mapped_column(String(1024))
    target_bucket: Mapped[str | None] = mapped_column(String(255))
    target_key: Mapped[str | None] = mapped_column(String(1024))
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    target_fingerprint: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
