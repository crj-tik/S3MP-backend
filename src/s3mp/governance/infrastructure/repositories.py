"""SQLAlchemy repositories for quota and audit."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.governance.infrastructure.models import QuotaModel


class SqlAlchemyQuotaStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_quotas(
        self, tenant_id: UUID, storage_space_id: str | None
    ) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = select(QuotaModel).where(QuotaModel.tenant_id == tenant_id)
            if storage_space_id:
                stmt = stmt.where(QuotaModel.storage_space_id == UUID(storage_space_id))
            rows = (await session.scalars(stmt.order_by(QuotaModel.updated_at.desc()))).all()
            return [_quota_dict(r) for r in rows]

    async def get_quota(self, tenant_id: UUID, quota_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(QuotaModel).where(
                    QuotaModel.tenant_id == tenant_id, QuotaModel.id == quota_id
                )
            )
            return _quota_dict(row) if row else None

    async def update_quota(
        self, tenant_id: UUID, quota_id: UUID, limit_bytes: int
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(QuotaModel)
                .where(QuotaModel.tenant_id == tenant_id, QuotaModel.id == quota_id)
                .with_for_update()
            )
            if row is None:
                return None
            row.limit_bytes = limit_bytes
            await session.flush()
            return _quota_dict(row)


class SqlAlchemyAuditStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_events(self, tenant_id: UUID, filters: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = (
                select(AuditEventModel)
                .where(AuditEventModel.tenant_id == tenant_id)
                .order_by(AuditEventModel.occurred_at.desc())
                .limit(50)
            )
            if filters.get("action"):
                stmt = stmt.where(AuditEventModel.action == filters["action"])
            if filters.get("actor_principal_id"):
                stmt = stmt.where(
                    AuditEventModel.actor_principal_id == UUID(filters["actor_principal_id"])
                )
            rows = (await session.scalars(stmt)).all()
            return [_audit_dict(r) for r in rows]

    async def get_event(self, tenant_id: UUID, event_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(AuditEventModel).where(
                    AuditEventModel.tenant_id == tenant_id,
                    AuditEventModel.id == event_id,
                )
            )
            return _audit_dict(row) if row else None


def _quota_dict(m: QuotaModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "storage_space_id": str(m.storage_space_id) if m.storage_space_id else None,
        "limit_bytes": m.limit_bytes,
        "used_bytes": m.used_bytes,
        "reserved_bytes": m.reserved_bytes,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _audit_dict(m: AuditEventModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "actor_principal_id": str(m.actor_principal_id) if m.actor_principal_id else None,
        "action": m.action,
        "resource_type": m.resource_type,
        "resource_id": m.resource_id,
        "details": m.details,
        "occurred_at": m.occurred_at.isoformat() if m.occurred_at else None,
    }
