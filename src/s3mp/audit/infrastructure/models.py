"""Append-only tenant-scoped audit persistence."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKeyConstraint, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from s3mp.common.database import Base


class AuditEventModel(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["tenant_id", "actor_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_audit_event_tenant_occurred", "tenant_id", "occurred_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    actor_principal_id: Mapped[UUID | None] = mapped_column()
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
