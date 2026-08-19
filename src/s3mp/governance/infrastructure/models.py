"""Durable quota state; services, not public APIs, mutate reservations."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from s3mp.common.database import Base


class QuotaModel(Base):
    __tablename__ = "quota"
    __table_args__ = (
        UniqueConstraint("tenant_id", "storage_space_id"),
        UniqueConstraint("tenant_id", "application_id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "storage_space_id"],
            ["storage_space.tenant_id", "storage_space.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "application_id"],
            ["application.tenant_id", "application.id"],
            ondelete="CASCADE",
        ),
        Index("ix_quota_tenant_application", "tenant_id", "application_id"),
        Index("ix_quota_tenant_status_mode", "tenant_id", "status", "allocation_mode"),
        Index("ix_quota_application_status", "application_id", "status"),
        Index(
            "uq_quota_active_tenant_total",
            "tenant_id",
            unique=True,
            postgresql_where=(
                "application_id IS NULL AND storage_space_id IS NULL AND status = 'active'"
            ),
        ),
        CheckConstraint(
            "allocation_mode IN ('tenant_total', 'application_reserved', 'storage_space_legacy')",
            name="ck_quota_allocation_mode",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended', 'revoked', 'legacy')",
            name="ck_quota_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    storage_space_id: Mapped[UUID | None] = mapped_column()
    application_id: Mapped[UUID | None] = mapped_column()
    limit_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    consistency_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="realtime", server_default="realtime"
    )
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reconciliation_run_id: Mapped[UUID | None] = mapped_column()
    drift_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    allocation_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="tenant_total", server_default="tenant_total"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QuotaReservationModel(Base):
    __tablename__ = "quota_reservation"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "quota_id"], ["quota.tenant_id", "quota.id"], ondelete="CASCADE"
        ),
        Index("ix_quota_reservation_tenant_status", "tenant_id", "status"),
        CheckConstraint(
            "allocation_mode IN ('shared_pool', 'application_reserved', 'storage_space_legacy')",
            name="ck_quota_reservation_allocation_mode",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    quota_id: Mapped[UUID] = mapped_column(nullable=False)
    application_quota_id: Mapped[UUID | None] = mapped_column()
    tenant_quota_id: Mapped[UUID | None] = mapped_column()
    allocation_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="shared_pool", server_default="shared_pool"
    )
    requested_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_bytes: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="reserved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuotaReconciliationRunModel(Base):
    __tablename__ = "quota_reconciliation_run"
    __table_args__ = (
        Index("ix_quota_reconciliation_run_tenant_created", "tenant_id", "created_at"),
        UniqueConstraint("tenant_id", "idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column()
    application_id: Mapped[UUID | None] = mapped_column()
    storage_space_id: Mapped[UUID | None] = mapped_column()
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="audit")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    provider_cursor: Mapped[str | None] = mapped_column(String(2048))
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(1024))
    summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuotaReconciliationDifferenceModel(Base):
    __tablename__ = "quota_reconciliation_difference"
    __table_args__ = (Index("ix_quota_reconciliation_difference_run_kind", "run_id", "kind"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column()
    application_id: Mapped[UUID | None] = mapped_column()
    storage_space_id: Mapped[UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    physical_key_fingerprint: Mapped[str | None] = mapped_column(String(64))
    recorded_bytes: Mapped[int | None] = mapped_column()
    observed_bytes: Mapped[int | None] = mapped_column()
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuotaAdjustmentModel(Base):
    __tablename__ = "quota_adjustment"
    __table_args__ = (
        Index("ix_quota_adjustment_tenant_created", "tenant_id", "created_at"),
        Index("ix_quota_adjustment_idempotency", "idempotency_key", unique=True),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    quota_id: Mapped[UUID] = mapped_column(nullable=False)
    file_object_id: Mapped[UUID | None] = mapped_column()
    reconciliation_run_id: Mapped[UUID | None] = mapped_column()
    delta_bytes: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
