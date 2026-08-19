"""SQLAlchemy repositories for quota and audit."""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.applications.infrastructure.models import ApplicationModel
from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.common.errors import ApiError
from s3mp.governance.domain.allocation import AllocationSnapshot, build_snapshot
from s3mp.governance.domain.quota import QuotaAllocationMode, QuotaScope
from s3mp.governance.domain.units import bytes_to_gib
from s3mp.governance.infrastructure.models import QuotaModel
from s3mp.identity.infrastructure.models import PrincipalModel
from s3mp.platform.infrastructure.models import PlatformAuditEventModel
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
        status: str | None = "active",
        allocation_mode: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        async with self._sf() as session:
            active_owner = or_(
                and_(QuotaModel.application_id.is_(None), QuotaModel.storage_space_id.is_(None)),
                and_(
                    QuotaModel.application_id.is_not(None),
                    exists(
                        select(ApplicationModel.id).where(
                            ApplicationModel.tenant_id == QuotaModel.tenant_id,
                            ApplicationModel.id == QuotaModel.application_id,
                            ApplicationModel.status == "active",
                        )
                    ),
                ),
                and_(
                    QuotaModel.storage_space_id.is_not(None),
                    exists(
                        select(StorageSpaceModel.id).where(
                            StorageSpaceModel.tenant_id == QuotaModel.tenant_id,
                            StorageSpaceModel.id == QuotaModel.storage_space_id,
                            StorageSpaceModel.status == "active",
                        )
                    ),
                ),
            )
            stmt = select(QuotaModel).where(
                QuotaModel.tenant_id == tenant_id,
                exists(
                    select(TenantModel.id).where(
                        TenantModel.id == QuotaModel.tenant_id,
                        TenantModel.status == "active",
                    )
                ),
                active_owner,
            )
            if status is not None:
                stmt = stmt.where(QuotaModel.status == status)
            if allocation_mode is not None:
                stmt = stmt.where(QuotaModel.allocation_mode == allocation_mode)
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
            views = [await self._quota_view(session, row) for row in page]
            return views, str(page[-1].id) if extra and page else None

    async def get_quota(self, tenant_id: UUID, quota_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(QuotaModel).where(
                    QuotaModel.tenant_id == tenant_id,
                    QuotaModel.id == quota_id,
                    QuotaModel.status == "active",
                    exists(
                        select(TenantModel.id).where(
                            TenantModel.id == QuotaModel.tenant_id,
                            TenantModel.status == "active",
                        )
                    ),
                )
            )
            return await self._quota_view(session, row) if row else None

    async def list_platform_quotas(
        self,
        *,
        tenant_id: UUID | None,
        application_id: UUID | None,
        status: str | None,
        allocation_mode: QuotaAllocationMode | None,
        limit: int,
        cursor: UUID | None,
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        async with self._sf() as session:
            stmt = select(QuotaModel)
            if tenant_id is not None:
                stmt = stmt.where(QuotaModel.tenant_id == tenant_id)
            if application_id is not None:
                stmt = stmt.where(QuotaModel.application_id == application_id)
            if status is not None:
                stmt = stmt.where(QuotaModel.status == status)
            if allocation_mode is not None:
                stmt = stmt.where(QuotaModel.allocation_mode == allocation_mode)
            if cursor is not None:
                stmt = stmt.where(QuotaModel.id > cursor)
            rows = list(
                (await session.scalars(stmt.order_by(QuotaModel.id).limit(limit + 1))).all()
            )
            page = rows[:limit]
            return [await self._quota_view(session, row) for row in page], (
                page[-1].id if len(rows) > limit and page else None
            )

    async def create_platform_quota(
        self,
        *,
        actor_user_id: UUID,
        tenant_id: UUID,
        application_id: UUID | None,
        limit_bytes: int,
        bucket_capacity_bytes: int | None,
    ) -> dict[str, Any]:
        if limit_bytes < 0:
            raise ApiError("validation_failed", "Quota limit must not be negative", 422)
        async with self._sf.begin() as session:
            tenant = await session.scalar(
                select(TenantModel)
                .where(TenantModel.id == tenant_id, TenantModel.status == "active")
                .with_for_update()
            )
            if tenant is None:
                raise ApiError("resource_not_found", "Active tenant not found", 404)
            tenant_quota = await self._lock_tenant_quota(session, tenant_id)
            if application_id is None:
                if bucket_capacity_bytes is not None and limit_bytes > bucket_capacity_bytes:
                    raise ApiError(
                        "quota_allocation_exceeded", "Tenant quota exceeds Bucket capacity", 422
                    )
                if tenant_quota is None:
                    tenant_quota = QuotaModel(
                        tenant_id=tenant_id,
                        limit_bytes=limit_bytes,
                        allocation_mode="tenant_total",
                        status="active",
                    )
                    session.add(tenant_quota)
                else:
                    self._validate_limit_floor(tenant_quota, limit_bytes)
                    tenant_quota.limit_bytes = limit_bytes
                    tenant_quota.status = "active"
                await session.flush()
                await self._audit_quota(
                    session, actor_user_id, tenant_id, tenant_quota, "quota.tenant_allocated"
                )
                return await self._quota_view(session, tenant_quota)

            application = await session.scalar(
                select(ApplicationModel)
                .where(
                    ApplicationModel.tenant_id == tenant_id,
                    ApplicationModel.id == application_id,
                    ApplicationModel.status == "active",
                )
                .with_for_update()
            )
            if application is None:
                raise ApiError("resource_not_found", "Active application not found", 404)
            if tenant_quota is None:
                raise ApiError("quota_not_configured", "Tenant quota must be configured first", 409)
            allocations = await self._lock_application_quotas(
                session, tenant_id, exclude=application_id
            )
            if sum(row.limit_bytes for row in allocations) + limit_bytes > tenant_quota.limit_bytes:
                raise ApiError(
                    "quota_allocation_exceeded", "Application allocations exceed tenant quota", 422
                )
            row = await session.scalar(
                select(QuotaModel)
                .where(
                    QuotaModel.tenant_id == tenant_id, QuotaModel.application_id == application_id
                )
                .with_for_update()
            )
            if row is None:
                row = QuotaModel(
                    tenant_id=tenant_id,
                    application_id=application_id,
                    limit_bytes=limit_bytes,
                    allocation_mode="application_reserved",
                    status="active",
                )
                session.add(row)
            else:
                self._validate_limit_floor(row, limit_bytes)
                row.limit_bytes = limit_bytes
                row.allocation_mode = "application_reserved"
                row.status = "active"
            await session.flush()
            await self._audit_quota(
                session, actor_user_id, tenant_id, row, "quota.application_allocated"
            )
            return await self._quota_view(session, row)

    async def revoke_platform_quota(
        self, *, actor_user_id: UUID, quota_id: UUID
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(QuotaModel).where(QuotaModel.id == quota_id).with_for_update()
            )
            if row is None or row.status != "active":
                return None
            if row.application_id is None:
                raise ApiError("quota_not_revokeable", "Tenant total quota cannot be revoked", 409)
            if row.used_bytes or row.reserved_bytes:
                raise ApiError("quota_in_use", "Application quota has usage or reservations", 409)
            row.status = "revoked"
            row.allocation_mode = "application_reserved"
            await session.flush()
            await self._audit_quota(
                session, actor_user_id, row.tenant_id, row, "quota.application_revoked"
            )
            return await self._quota_view(session, row)

    async def update_platform_quota(
        self,
        actor_user_id: UUID,
        quota_id: UUID,
        limit_bytes: int,
        bucket_capacity_bytes: int | None,
    ) -> dict[str, Any] | None:
        if limit_bytes < 0:
            raise ApiError("validation_failed", "Quota limit must not be negative", 422)
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(QuotaModel).where(QuotaModel.id == quota_id).with_for_update()
            )
            if row is None or row.status != "active":
                return None
            if row.application_id is None and row.storage_space_id is None:
                if bucket_capacity_bytes is not None and limit_bytes > bucket_capacity_bytes:
                    raise ApiError(
                        "quota_allocation_exceeded", "Tenant quota exceeds Bucket capacity", 422
                    )
                tenant_quota: QuotaModel | None = row
                allocations = await self._lock_application_quotas(session, row.tenant_id)
                assert tenant_quota is not None
                if limit_bytes < max(
                    tenant_quota.used_bytes,
                    tenant_quota.reserved_bytes,
                    sum(q.limit_bytes for q in allocations),
                ):
                    raise ApiError(
                        "quota_limit_too_low",
                        "Tenant quota is below active usage or allocations",
                        422,
                    )
            else:
                tenant_quota = await self._lock_tenant_quota(
                    session, row.tenant_id
                )
                allocations = await self._lock_application_quotas(
                    session, row.tenant_id, exclude=row.application_id
                )
                if (
                    tenant_quota is None
                    or sum(q.limit_bytes for q in allocations) + limit_bytes
                    > tenant_quota.limit_bytes
                ):
                    raise ApiError(
                        "quota_allocation_exceeded",
                        "Application allocations exceed tenant quota",
                        422,
                    )
                self._validate_limit_floor(row, limit_bytes)
            row.limit_bytes = limit_bytes
            await session.flush()
            await self._audit_quota(session, actor_user_id, row.tenant_id, row, "quota.updated")
            return await self._quota_view(session, row)

    async def _lock_tenant_quota(self, session: AsyncSession, tenant_id: UUID) -> QuotaModel | None:
        return cast(
            QuotaModel | None,
            await session.scalar(
                select(QuotaModel)
                .where(
                    QuotaModel.tenant_id == tenant_id,
                    QuotaModel.application_id.is_(None),
                    QuotaModel.storage_space_id.is_(None),
                    QuotaModel.status == "active",
                )
                .with_for_update()
            ),
        )

    async def _lock_application_quotas(
        self, session: AsyncSession, tenant_id: UUID, *, exclude: UUID | None = None
    ) -> list[QuotaModel]:
        stmt = (
            select(QuotaModel)
            .where(
                QuotaModel.tenant_id == tenant_id,
                QuotaModel.application_id.is_not(None),
                QuotaModel.status == "active",
            )
            .order_by(QuotaModel.id)
            .with_for_update()
        )
        rows = list((await session.scalars(stmt)).all())
        return [row for row in rows if exclude is None or row.application_id != exclude]

    @staticmethod
    def _validate_limit_floor(row: QuotaModel, limit_bytes: int) -> None:
        if limit_bytes < max(row.used_bytes, row.reserved_bytes):
            raise ApiError("quota_limit_too_low", "Quota limit is below usage or reservations", 422)

    async def _quota_view(self, session: AsyncSession, row: QuotaModel) -> dict[str, Any]:
        applications = list(
            (
                await session.scalars(
                    select(QuotaModel).where(
                        QuotaModel.tenant_id == row.tenant_id,
                        QuotaModel.application_id.is_not(None),
                        QuotaModel.status == "active",
                    )
                )
            ).all()
        )
        tenant = (
            row
            if row.application_id is None and row.storage_space_id is None
            else await session.scalar(
                select(QuotaModel).where(
                    QuotaModel.tenant_id == row.tenant_id,
                    QuotaModel.application_id.is_(None),
                    QuotaModel.storage_space_id.is_(None),
                    QuotaModel.status == "active",
                )
            )
        )
        snapshot = build_snapshot(tenant, applications) if tenant else None
        return _quota_dict(row, snapshot)

    @staticmethod
    async def _audit_quota(
        session: AsyncSession, actor_user_id: UUID, tenant_id: UUID, row: QuotaModel, action: str
    ) -> None:
        session.add(
            PlatformAuditEventModel(
                actor_user_id=actor_user_id,
                action=action,
                resource_type="quota",
                resource_id=str(row.id),
                details={
                    "tenant_id": str(tenant_id),
                    "application_id": str(row.application_id) if row.application_id else None,
                    "limit_bytes": row.limit_bytes,
                    "status": row.status,
                },
            )
        )

    async def update_quota(
        self, tenant_id: UUID, quota_id: UUID, limit_bytes: int
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(QuotaModel)
                .where(QuotaModel.tenant_id == tenant_id, QuotaModel.id == quota_id)
                .with_for_update()
            )
            if row is None or row.status != "active":
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
                        QuotaModel.status == "active",
                    )
                    .with_for_update()
                )
                allocations = await self._lock_application_quotas(
                    session, tenant_id, exclude=row.application_id
                )
                if (
                    tenant_quota is not None
                    and sum(q.limit_bytes for q in allocations) + limit_bytes
                    > tenant_quota.limit_bytes
                ):
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
            else:
                allocations = await self._lock_application_quotas(session, tenant_id)
                if limit_bytes < max(
                    row.used_bytes,
                    row.reserved_bytes,
                    sum(q.limit_bytes for q in allocations),
                ):
                    raise ApiError(
                        "quota_limit_too_low",
                        "Tenant quota is below active usage or allocations",
                        status_code=422,
                    )
            row.limit_bytes = limit_bytes
            await session.flush()
            return await self._quota_view(session, row)


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
            stmt = (
                select(AuditEventModel, PrincipalModel.type)
                .outerjoin(
                    PrincipalModel,
                    and_(
                        PrincipalModel.tenant_id == AuditEventModel.tenant_id,
                        PrincipalModel.id == AuditEventModel.actor_principal_id,
                    ),
                )
                .where(AuditEventModel.tenant_id == tenant_id)
            )
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
            row = (
                await session.execute(
                    select(AuditEventModel, PrincipalModel.type)
                    .outerjoin(
                        PrincipalModel,
                        and_(
                            PrincipalModel.tenant_id == AuditEventModel.tenant_id,
                            PrincipalModel.id == AuditEventModel.actor_principal_id,
                        ),
                    )
                    .where(
                        AuditEventModel.tenant_id == tenant_id,
                        AuditEventModel.id == event_id,
                    )
                )
            ).first()
            return _audit_dict(row[0], row[1]) if row else None


def _quota_dict(m: QuotaModel, snapshot: AllocationSnapshot | None = None) -> dict[str, Any]:
    result = {
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
            (m.measured_at or m.updated_at).isoformat() if (m.measured_at or m.updated_at) else None
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
        "allocation_mode": getattr(m, "allocation_mode", "tenant_total"),
        "status": getattr(m, "status", "active"),
        "allocated_bytes": sum(
            max(int(getattr(m, field, 0)), 0) for field in ("used_bytes", "reserved_bytes")
        ),
        **(snapshot.as_dict() if snapshot else {}),
    }
    for key, value in list(result.items()):
        if key.endswith("_bytes") and isinstance(value, int):
            result[key.removesuffix("_bytes") + "_gib"] = bytes_to_gib(int(value))
    allocated_bytes = result.get("allocated_bytes")
    if isinstance(allocated_bytes, int):
        result["allocated_gib"] = bytes_to_gib(allocated_bytes)
    return result


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
