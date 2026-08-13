"""SQLAlchemy persistence models for tenants."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from s3mp.common.database import Base
from s3mp.platform.infrastructure.models import TenantLifecycleStatus


class TenantModel(Base):
    """Top-level tenant boundary."""

    __tablename__ = "tenant"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[TenantLifecycleStatus] = mapped_column(
        Enum(
            TenantLifecycleStatus,
            name="tenant_lifecycle_status",
            native_enum=False,
            values_callable=list,
        ),
        nullable=False,
        default=TenantLifecycleStatus.ACTIVE,
        server_default=TenantLifecycleStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
