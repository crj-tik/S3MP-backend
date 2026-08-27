"""Read/write projections used by the tenant dashboard."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.applications.infrastructure.models import ApplicationModel
from s3mp.files.infrastructure.models import FileObjectModel
from s3mp.governance.infrastructure.models import (
    ApplicationApiErrorModel,
    ApplicationApiMetricModel,
    TenantStorageSummaryModel,
)
from s3mp.tenant.infrastructure.models import TenantModel


class SqlAlchemyDashboardStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def refresh_storage_summaries(self) -> int:
        """Refresh all active tenants in one bounded aggregate statement."""
        now = datetime.now(UTC)
        async with self._sf.begin() as session:
            rows = await session.execute(
                select(
                    TenantModel.id,
                    func.coalesce(
                        func.sum(
                            case(
                                (FileObjectModel.soft_deleted.is_(False), 1), else_=0
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    FileObjectModel.status != "deleted",
                                    FileObjectModel.content_length,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    (FileObjectModel.soft_deleted.is_(True))
                                    & (FileObjectModel.status != "deleted"),
                                    FileObjectModel.content_length,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
                .outerjoin(FileObjectModel, FileObjectModel.tenant_id == TenantModel.id)
                .where(TenantModel.status == "active")
                .group_by(TenantModel.id)
            )
            count = 0
            for tenant_id, file_count, occupied, pending_cleanup in rows:
                stmt = insert(TenantStorageSummaryModel).values(
                    tenant_id=tenant_id,
                    active_file_count=int(file_count),
                    occupied_bytes=int(occupied),
                    pending_cleanup_bytes=int(pending_cleanup),
                    generated_at=now,
                )
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["tenant_id"],
                        set_={
                            "active_file_count": stmt.excluded.active_file_count,
                            "occupied_bytes": stmt.excluded.occupied_bytes,
                            "pending_cleanup_bytes": stmt.excluded.pending_cleanup_bytes,
                            "generated_at": stmt.excluded.generated_at,
                        },
                    )
                )
                count += 1
            return count

    async def overview(self, tenant_id: UUID) -> dict[str, object]:
        since = datetime.now(UTC) - timedelta(hours=24)
        async with self._sf() as session:
            summary = await session.get(TenantStorageSummaryModel, tenant_id)
            app_count = await session.scalar(
                select(func.count()).select_from(ApplicationModel).where(
                    ApplicationModel.tenant_id == tenant_id, ApplicationModel.status == "active"
                )
            )
            totals = (await session.execute(
                select(
                    func.coalesce(func.sum(ApplicationApiMetricModel.total_count), 0),
                    func.coalesce(func.sum(ApplicationApiMetricModel.success_count), 0),
                    func.coalesce(func.sum(ApplicationApiMetricModel.client_error_count), 0)
                    + func.coalesce(func.sum(ApplicationApiMetricModel.server_error_count), 0),
                    func.count(func.distinct(ApplicationApiMetricModel.application_id)),
                ).where(
                    ApplicationApiMetricModel.tenant_id == tenant_id,
                    ApplicationApiMetricModel.window_start >= since,
                )
            )).one()
            top = (await session.execute(
                select(
                    ApplicationApiMetricModel.operation,
                    func.sum(ApplicationApiMetricModel.total_count).label("count"),
                )
                .where(
                    ApplicationApiMetricModel.tenant_id == tenant_id,
                    ApplicationApiMetricModel.window_start >= since,
                )
                .group_by(ApplicationApiMetricModel.operation)
                .order_by(func.sum(ApplicationApiMetricModel.total_count).desc())
                .limit(3)
            )).all()
            return {
                "application_count": int(app_count or 0),
                "storage": None if summary is None else {
                    "active_file_count": summary.active_file_count,
                    "occupied_bytes": summary.occupied_bytes,
                    "pending_cleanup_bytes": summary.pending_cleanup_bytes,
                    "generated_at": summary.generated_at,
                },
                "api_usage": {
                    "total_calls": int(totals[0]), "success_calls": int(totals[1]),
                    "abnormal_calls": int(totals[2]), "active_applications": int(totals[3]),
                    "top_operations": [{"operation": row[0], "count": int(row[1])} for row in top],
                },
            }

    async def list_api_metrics(
        self,
        tenant_id: UUID,
        *,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        application_id: UUID | None = None,
        operation: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        predicates = [ApplicationApiMetricModel.tenant_id == tenant_id]
        if occurred_from is not None:
            predicates.append(ApplicationApiMetricModel.window_start >= occurred_from)
        if occurred_to is not None:
            predicates.append(ApplicationApiMetricModel.window_start < occurred_to)
        if application_id is not None:
            predicates.append(ApplicationApiMetricModel.application_id == application_id)
        if operation:
            predicates.append(ApplicationApiMetricModel.operation == operation)
        async with self._sf() as session:
            rows = (await session.execute(
                select(
                    ApplicationApiMetricModel.application_id,
                    ApplicationApiMetricModel.operation,
                    func.sum(ApplicationApiMetricModel.total_count).label("total_count"),
                    func.sum(ApplicationApiMetricModel.success_count).label("success_count"),
                    func.sum(ApplicationApiMetricModel.client_error_count).label("client_error_count"),
                    func.sum(ApplicationApiMetricModel.server_error_count).label("server_error_count"),
                )
                .where(*predicates)
                .group_by(
                    ApplicationApiMetricModel.application_id,
                    ApplicationApiMetricModel.operation,
                )
                .order_by(func.sum(ApplicationApiMetricModel.total_count).desc())
                .offset(offset)
                .limit(limit)
            )).all()
        return [
            {
                "application_id": str(row.application_id),
                "operation": row.operation,
                "total_count": int(row.total_count),
                "success_count": int(row.success_count),
                "client_error_count": int(row.client_error_count),
                "server_error_count": int(row.server_error_count),
            }
            for row in rows
        ]

    async def list_api_errors(
        self,
        tenant_id: UUID,
        *,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        application_id: UUID | None = None,
        operation: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        predicates = [ApplicationApiErrorModel.tenant_id == tenant_id]
        if occurred_from is not None:
            predicates.append(ApplicationApiErrorModel.occurred_at >= occurred_from)
        if occurred_to is not None:
            predicates.append(ApplicationApiErrorModel.occurred_at < occurred_to)
        if application_id is not None:
            predicates.append(ApplicationApiErrorModel.application_id == application_id)
        if operation:
            predicates.append(ApplicationApiErrorModel.operation == operation)
        async with self._sf() as session:
            rows = (await session.scalars(
                select(ApplicationApiErrorModel)
                .where(*predicates)
                .order_by(ApplicationApiErrorModel.occurred_at.desc()).offset(offset).limit(limit)
            )).all()
            return [{"operation": row.operation, "status_code": row.status_code,
                     "request_id": row.request_id, "occurred_at": row.occurred_at,
                     "application_id": str(row.application_id)} for row in rows]
