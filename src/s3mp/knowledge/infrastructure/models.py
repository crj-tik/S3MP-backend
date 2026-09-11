"""Tenant-scoped durable state for S3-backed knowledge extraction."""

from datetime import datetime
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from s3mp.common.database import Base


class KnowledgeAnalysisTaskModel(Base):
    __tablename__ = "knowledge_analysis_task"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_file_id", "contract_manifest_hash"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["source_file_id"], ["file_object.id"], ondelete="SET NULL"),
        Index("ix_knowledge_analysis_task_pending", "state", "created_at"),
        Index("ix_knowledge_analysis_task_source_hash", "tenant_id", "source_sha256"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    source_file_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_application_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_storage_space_id: Mapped[UUID | None] = mapped_column(nullable=True)
    source_storage_namespace: Mapped[str | None] = mapped_column(String(1024))
    source_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    source_content_hash: Mapped[str | None] = mapped_column(String(512))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    phase: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    recovery_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_lease_token: Mapped[UUID | None] = mapped_column()
    processing_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    batch_id: Mapped[str | None] = mapped_column(String(64))
    batch_prefix: Mapped[str | None] = mapped_column(String(2048))
    failure_reason: Mapped[str | None] = mapped_column(String(256))
    diagnostics: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeExtractionExclusionRuleModel(Base):
    __tablename__ = "knowledge_extraction_exclusion_rule"
    __table_args__ = (
        UniqueConstraint("tenant_id", "application_id", "directory_path", "rule_source"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
        Index("ix_knowledge_exclusion_rule_match", "tenant_id", "application_id", "enabled"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    application_id: Mapped[UUID] = mapped_column(nullable=False)
    directory_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    rule_source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_principal_id: Mapped[UUID | None] = mapped_column()
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeBatchModel(Base):
    __tablename__ = "knowledge_batch"
    __table_args__ = (
        UniqueConstraint("tenant_id", "batch_id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["task_id"], ["knowledge_analysis_task.id"], ondelete="CASCADE"),
        Index("ix_knowledge_batch_task", "task_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    task_id: Mapped[UUID] = mapped_column(nullable=False)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    s3_prefix: Mapped[str] = mapped_column(String(2048), nullable=False)
    completion_manifest_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    completion_manifest_checksum: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeCardModel(Base):
    __tablename__ = "knowledge_card"
    __table_args__ = (
        UniqueConstraint("tenant_id", "batch_id", "card_id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["batch_id"], ["knowledge_batch.id"], ondelete="CASCADE"),
        Index("ix_knowledge_card_tenant_card", "tenant_id", "card_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    batch_id: Mapped[UUID] = mapped_column(nullable=False)
    card_id: Mapped[str] = mapped_column(String(256), nullable=False)
    card_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64))
    source_locations: Mapped[list[object]] = mapped_column(JSON, nullable=False, default=list)
    index_state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeEventOutboxModel(Base):
    __tablename__ = "knowledge_event_outbox"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["task_id"], ["knowledge_analysis_task.id"], ondelete="CASCADE"),
        Index("ix_knowledge_event_outbox_pending", "published_at", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    task_id: Mapped[UUID] = mapped_column(nullable=False)
    card_id: Mapped[UUID | None] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    publish_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    publish_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeDeadLetterEventModel(Base):
    __tablename__ = "knowledge_dead_letter_event"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["task_id"], ["knowledge_analysis_task.id"], ondelete="SET NULL"),
        Index("ix_knowledge_dead_letter_task", "task_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    task_id: Mapped[UUID | None] = mapped_column()
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
