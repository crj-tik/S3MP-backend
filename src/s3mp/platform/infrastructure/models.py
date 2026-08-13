"""SQLAlchemy models for global platform authority and browser account sessions."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from s3mp.common.database import Base


class TenantLifecycleStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class PlatformRoleModel(Base):
    __tablename__ = "platform_role"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    built_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformRoleBindingModel(Base):
    __tablename__ = "platform_role_binding"
    __table_args__ = (Index("ix_platform_role_binding_user_expiry", "user_id", "expires_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    role_id: Mapped[UUID] = mapped_column(ForeignKey("platform_role.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformBootstrapStateModel(Base):
    """A single row serializes the irreversible first-admin transition."""

    __tablename__ = "platform_bootstrap_state"

    singleton: Mapped[bool] = mapped_column(Boolean, primary_key=True, default=True)
    initialized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PlatformAuditEventModel(Base):
    __tablename__ = "platform_audit_event"
    __table_args__ = (
        Index("ix_platform_audit_event_actor_created", "actor_user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(120))
    details: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountSessionModel(Base):
    __tablename__ = "account_session"
    __table_args__ = (
        Index("ix_account_session_user_expires", "user_id", "expires_at"),
        Index("ix_account_session_expires", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(64), unique=True)
    csrf_digest: Mapped[bytes] = mapped_column(LargeBinary(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SupportAccessRequestModel(Base):
    __tablename__ = "support_access_request"
    __table_args__ = (Index("ix_support_access_request_tenant_expiry", "tenant_id", "expires_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    requester_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT")
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="RESTRICT")
    )
    membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("membership.id", ondelete="SET NULL")
    )
    role_binding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("role_binding.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
