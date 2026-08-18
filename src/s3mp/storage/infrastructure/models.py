"""Persistence models for tenant-scoped S3 connections and spaces."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
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


class PlatformStorageProfileModel(Base):
    """Platform-owned shared provider target for every tenant and application."""

    __tablename__ = "platform_storage_profile"
    __table_args__ = (
        UniqueConstraint("id"),
        Index("ix_platform_storage_profile_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    path_style: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    signature_version: Mapped[str] = mapped_column(String(32), nullable=False, default="s3v4")
    credential_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StorageConnectionModel(Base):
    __tablename__ = "storage_connection"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "name"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        Index("ix_storage_connection_tenant_status", "tenant_id", "status"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    path_style: Mapped[bool] = mapped_column(nullable=False, default=True)
    credential_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    capabilities: Mapped[dict[str, bool]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StorageSpaceModel(Base):
    __tablename__ = "storage_space"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "name"),
        ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["tenant_id", "connection_id"],
            ["storage_connection.tenant_id", "storage_connection.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "application_id"],
            ["application.tenant_id", "application.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "application_id"),
        Index("ix_storage_space_tenant_connection", "tenant_id", "connection_id"),
        Index("ix_storage_space_tenant_application", "tenant_id", "application_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    connection_id: Mapped[UUID] = mapped_column(nullable=False)
    application_id: Mapped[UUID | None] = mapped_column(nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    root_prefix: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    storage_namespace: Mapped[str | None] = mapped_column(String(512), nullable=True)
    profile_version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    provider_target_version: Mapped[int] = mapped_column(nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
