"""SQLAlchemy repositories for quota and audit."""

from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.applications.infrastructure.models import ApplicationModel
from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.common.errors import ApiError
from s3mp.governance.domain.quota import QuotaScope
from s3mp.governance.infrastructure.models import QuotaModel
from s3mp.identity.infrastructure.models import PrincipalModel
from s3mp.storage.infrastructure.models import StorageSpaceModel
from s3mp.tenant.infrastructure.models import TenantModel


class SqlAlchemyQuotaStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_quotas(
        self,
        tenant_id: UUID,
        storage_space_id: str | None,
        limit: int = 50,
        cursor: str | None = None,
        application_id: str | None = None,
        scope: QuotaScope | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        async with self._sf() as session:
            stmt = select(QuotaModel).where(QuotaModel.tenant_id == tenant_id)
            if storage_space_id:
                stmt = stmt.where(QuotaModel.storage_space_id == UUID(storage_space_id))
            if application_id:
                stmt = stmt.where(QuotaModel.application_id == UUID(application_id))
            if scope is QuotaScope.TENANT:
                stmt = stmt.where(QuotaModel.application_id.is_(None))
            elif scope is QuotaScope.APPLICATION:
                stmt = stmt.where(QuotaModel.application_id.is_not(None))
            elif scope is QuotaScope.STORAGE_SPACE:
                stmt = stmt.where(
                    QuotaModel.storage_space_id.is_not(None),
                    QuotaModel.application_id.is_(None),
                )
            if cursor:
                stmt = stmt.where(QuotaModel.id > UUID(cursor))
            rows = (await session.scalars(stmt.order_by(QuotaModel.id).limit(limit + 1))).all()
        page, extra = rows[:limit], len(rows) > limit
        return [_quota_dict(row) for row in page], str(page[-1].id) if extra and page else None

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
            tenant = await session.scalar(
                select(TenantModel)
                .where(TenantModel.id == tenant_id, TenantModel.status == "active")
                .with_for_update()
            )
            if tenant is None:
                return None
            if row.application_id is not None:
                application = await session.scalar(
                    select(ApplicationModel)
                    .where(
                        ApplicationModel.tenant_id == tenant_id,
                        ApplicationModel.id == row.application_id,
                        ApplicationModel.status == "active",
                    )
                    .with_for_update()
                )
                if application is None:
                    return None
                tenant_quota = await session.scalar(
                    select(QuotaModel)
                    .where(
                        QuotaModel.tenant_id == tenant_id,
                        QuotaModel.application_id.is_(None),
                        QuotaModel.storage_space_id.is_(None),
                    )
                    .with_for_update()
                )
                if tenant_quota is not None and limit_bytes > tenant_quota.limit_bytes:
                    raise ApiError(
                        "quota_allocation_exceeded",
                        "Application quota cannot exceed tenant quota",
                        status_code=422,
                    )
            elif row.storage_space_id is not None:
                space = await session.scalar(
                    select(StorageSpaceModel)
                    .where(
                        StorageSpaceModel.tenant_id == tenant_id,
                        StorageSpaceModel.id == row.storage_space_id,
                        StorageSpaceModel.status == "active",
                    )
                    .with_for_update()
                )
                if space is None:
                    return None
                tenant_quota = await session.scalar(
                    select(QuotaModel)
                    .where(
                        QuotaModel.tenant_id == tenant_id,
                        QuotaModel.application_id.is_(None),
                        QuotaModel.storage_space_id.is_(None),
                    )
                    .with_for_update()
                )
                if tenant_quota is not None and limit_bytes > tenant_quota.limit_bytes:
                    raise ApiError(
                        "quota_allocation_exceeded",
                        "Storage space quota cannot exceed tenant quota",
                        status_code=422,
                    )
            row.limit_bytes = limit_bytes
            await session.flush()
            return _quota_dict(row)


class SqlAlchemyAuditStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def list_events(
        self,
        tenant_id: UUID,
        filters: dict[str, Any],
        limit: int = 50,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        async with self._sf() as session:
            stmt = select(AuditEventModel, PrincipalModel.type).outerjoin(
                PrincipalModel,
                and_(
                    PrincipalModel.tenant_id == AuditEventModel.tenant_id,
                    PrincipalModel.id == AuditEventModel.actor_principal_id,
                ),
            ).where(AuditEventModel.tenant_id == tenant_id)
            if filters.get("action"):
                stmt = stmt.where(AuditEventModel.action == filters["action"])
            if filters.get("actor_principal_id"):
                stmt = stmt.where(
                    AuditEventModel.actor_principal_id == UUID(filters["actor_principal_id"])
                )
            if cursor:
                stmt = stmt.where(AuditEventModel.id > UUID(cursor))
            rows = (await session.execute(stmt.order_by(AuditEventModel.id).limit(limit + 1))).all()
        page, extra = rows[:limit], len(rows) > limit
        views = [_audit_dict(row[0], row[1]) for row in page]
        position = str(page[-1][0].id) if extra and page else None
        return views, position

    async def get_event(self, tenant_id: UUID, event_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = (await session.execute(
                select(AuditEventModel, PrincipalModel.type).outerjoin(
                    PrincipalModel,
                    and_(
                        PrincipalModel.tenant_id == AuditEventModel.tenant_id,
                        PrincipalModel.id == AuditEventModel.actor_principal_id,
                    ),
                ).where(
                    AuditEventModel.tenant_id == tenant_id,
                    AuditEventModel.id == event_id,
                )
            )).first()
            return _audit_dict(row[0], row[1]) if row else None


def _quota_dict(m: QuotaModel) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "storage_space_id": str(m.storage_space_id) if m.storage_space_id else None,
        "application_id": str(m.application_id) if m.application_id else None,
        "limit_bytes": m.limit_bytes,
        "used_bytes": m.used_bytes,
        "reserved_bytes": m.reserved_bytes,
        "available_bytes": max(
            (m.limit_bytes or 0) - (m.used_bytes or 0) - (m.reserved_bytes or 0), 0
        ),
        "consistency_status": m.consistency_status,
        "drift_summary": dict(m.drift_summary or {}),
        "measured_at": (
            (m.measured_at or m.updated_at).isoformat()
            if (m.measured_at or m.updated_at)
            else None
        ),
        "last_reconciliation_run_id": (
            str(m.last_reconciliation_run_id) if m.last_reconciliation_run_id else None
        ),
        "scope_type": (
            "application"
            if m.application_id
            else ("storage_space" if m.storage_space_id else "tenant")
        ),
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _audit_dict(m: AuditEventModel, principal_type: Any = None) -> dict[str, Any]:
    details = dict(m.details or {})
    actor = (
        {
            "principal_id": str(m.actor_principal_id),
            "principal_type": getattr(principal_type, "value", principal_type) or "unknown",
        }
        if m.actor_principal_id
        else None
    )
    return {
        "id": str(m.id),
        "tenant_id": str(m.tenant_id),
        "actor_principal_id": str(m.actor_principal_id) if m.actor_principal_id else None,
        "action": m.action,
        "resource_type": m.resource_type,
        "resource_id": m.resource_id,
        "details": details,
        "occurred_at": m.occurred_at.isoformat() if m.occurred_at else None,
        "actor": actor,
        "outcome": details.get("outcome"),
        "request_id": details.get("request_id"),
    }
