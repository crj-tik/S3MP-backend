"""Durable quota state; services, not public APIs, mutate reservations."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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


class QuotaModel(Base):
    __tablename__ = "quota"
    __table_args__ = (
        UniqueConstraint("tenant_id", "storage_space_id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "storage_space_id"],
            ["storage_space.tenant_id", "storage_space.id"],
            ondelete="CASCADE",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    storage_space_id: Mapped[UUID | None] = mapped_column()
    limit_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    used_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    quota_id: Mapped[UUID] = mapped_column(nullable=False)
    requested_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_bytes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="reserved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
