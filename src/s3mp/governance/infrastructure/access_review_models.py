"""SQLAlchemy models for access review, review items and approval requests."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from s3mp.common.database import Base


class AccessReviewModel(Base):
    __tablename__ = "access_review"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="SET NULL",
        ),
        Index("ix_access_review_tenant_status", "tenant_id", "status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_by_principal_id: Mapped[UUID | None] = mapped_column()
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ReviewItemModel(Base):
    __tablename__ = "review_item"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "review_id"],
            ["access_review.tenant_id", "access_review.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reviewer_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="SET NULL",
        ),
        Index("ix_review_item_review_verdict", "review_id", "verdict"),
        Index("ix_review_item_tenant_resource", "tenant_id", "resource_type", "resource_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    review_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")
    reviewer_principal_id: Mapped[UUID | None] = mapped_column()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ApprovalRequestModel(Base):
    __tablename__ = "approval_request"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "requester_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="RESTRICT",
            name="fk_approval_request_requester",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "approver_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="SET NULL",
            name="fk_approval_request_approver",
        ),
        Index("ix_approval_request_tenant_status", "tenant_id", "status"),
        Index("ix_approval_request_requester", "tenant_id", "requester_principal_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column()
    requester_principal_id: Mapped[UUID] = mapped_column(nullable=False)
    approver_principal_id: Mapped[UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )