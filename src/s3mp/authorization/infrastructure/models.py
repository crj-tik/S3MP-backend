"""SQLAlchemy models for tenant-scoped groups, roles and bindings."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
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


class BindingEffect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class GroupModel(Base):
    __tablename__ = "user_group"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="CASCADE",
        ),
        Index("ix_user_group_tenant_name", "tenant_id", "name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    principal_id: Mapped[UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=func.true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GroupMemberModel(Base):
    __tablename__ = "group_member"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "group_id", "principal_id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["user_group.tenant_id", "user_group.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="CASCADE",
        ),
        Index("ix_group_member_tenant_group", "tenant_id", "group_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    group_id: Mapped[UUID] = mapped_column(nullable=False)
    principal_id: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PermissionModel(Base):
    __tablename__ = "permission"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    delegable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class RoleModel(Base):
    __tablename__ = "role"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "name"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        Index("ix_role_tenant_name", "tenant_id", "name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    built_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RolePermissionModel(Base):
    __tablename__ = "role_permission"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id"),
        ForeignKeyConstraint(["role_id"], ["role.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["permission_id"], ["permission.id"], ondelete="CASCADE"),
    )

    role_id: Mapped[UUID] = mapped_column(primary_key=True)
    permission_id: Mapped[UUID] = mapped_column(primary_key=True)


class RoleBindingModel(Base):
    __tablename__ = "role_binding"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="CASCADE",
            name="fk_role_binding_principal",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["role.tenant_id", "role.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "created_by_principal_id"],
            ["principal.tenant_id", "principal.id"],
            ondelete="RESTRICT",
            name="fk_role_binding_created_by_principal",
        ),
        Index("ix_role_binding_tenant_principal", "tenant_id", "principal_id"),
        Index("ix_role_binding_tenant_scope", "tenant_id", "storage_space_id", "canonical_prefix"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    principal_id: Mapped[UUID] = mapped_column(nullable=False)
    role_id: Mapped[UUID] = mapped_column(nullable=False)
    effect: Mapped[BindingEffect] = mapped_column(String(10), nullable=False)
    storage_space_id: Mapped[UUID | None] = mapped_column()
    canonical_prefix: Mapped[str | None] = mapped_column(String(2048))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_principal_id: Mapped[UUID] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
