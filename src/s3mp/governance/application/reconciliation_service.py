"""Application service for safe, tenant-scoped quota reconciliation."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.common.errors import ApiError
from s3mp.files.infrastructure.models import FileObjectModel
from s3mp.governance.application.quota_reconciliation import (
    ReconciliationDifference,
    ReconciliationFile,
    ReconciliationObject,
    compare_inventory,
)
from s3mp.governance.infrastructure.models import (
    QuotaModel,
    QuotaReconciliationDifferenceModel,
    QuotaReconciliationRunModel,
)
from s3mp.identity.domain.context import PrincipalContext
from s3mp.storage.infrastructure.models import StorageSpaceModel


class InventoryProvider(Protocol):
    async def list_objects(
        self, prefix: str = "", *, continuation_token: str | None = None, max_keys: int = 1000
    ) -> tuple[list[Any], str | None]:
        raise NotImplementedError


@dataclass
class QuotaReconciliationService:
    session_factory: async_sessionmaker[AsyncSession]
    object_storage: InventoryProvider | None
    authorizer: Any

    async def reconcile(
        self,
        context: PrincipalContext | None,
        *,
        mode: str = "audit",
        application_id: str | None = None,
        storage_space_id: str | None = None,
        idempotency_key: str | None = None,
        internal_tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        if mode not in {"audit", "apply"}:
            raise ApiError("invalid_request", "mode must be audit or apply", status_code=422)
        if context is not None:
            await self.authorizer.require_permission(
                context, "quotas.manage" if mode == "apply" else "quotas.read"
            )
        if self.object_storage is None:
            raise ApiError("internal_error", "Object storage is not configured", status_code=500)
        app_id = UUID(application_id) if application_id else None
        space_id = UUID(storage_space_id) if storage_space_id else None
        if app_id and space_id:
            raise ApiError(
                "invalid_request",
                "application_id and storage_space_id are mutually exclusive",
                status_code=422,
            )

        tenant_id = context.tenant_id if context is not None else internal_tenant_id
        actor_id = context.principal_id if context is not None else None
        if tenant_id is None:
            raise ApiError(
                "invalid_request",
                "tenant_id is required for internal reconciliation",
                status_code=422,
            )
        async with self.session_factory() as session:
            # Session-scoped lock deliberately survives the per-page commits below.
            # A transaction-scoped lock would be released while persisting progress.
            await session.execute(select(func.pg_advisory_lock(_tenant_lock_key(tenant_id))))
            run: QuotaReconciliationRunModel | None = None
            run_id: UUID | None = None
            try:
                if idempotency_key is not None:
                    existing = await session.scalar(
                        select(QuotaReconciliationRunModel).where(
                            QuotaReconciliationRunModel.tenant_id == tenant_id,
                            QuotaReconciliationRunModel.idempotency_key == idempotency_key,
                        )
                    )
                    if existing is not None:
                        if (
                            existing.mode != mode
                            or existing.application_id != app_id
                            or existing.storage_space_id != space_id
                        ):
                            raise ApiError(
                                "idempotency_key_reused",
                                (
                                    "Idempotency key was already used with a different "
                                    "reconciliation scope"
                                ),
                                status_code=409,
                            )
                        return {
                            "id": str(existing.id),
                            "mode": existing.mode,
                            "status": existing.status,
                            **dict(existing.summary or {}),
                        }
                run = QuotaReconciliationRunModel(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    application_id=app_id,
                    storage_space_id=space_id,
                    mode=mode,
                    status="running",
                    idempotency_key=idempotency_key,
                    attempt_count=0,
                )
                session.add(run)
                session.add(
                    AuditEventModel(
                        tenant_id=tenant_id,
                        actor_principal_id=actor_id,
                        action="quota.reconciliation_started",
                        resource_type="quota_reconciliation_run",
                        resource_id=str(run.id),
                        details={
                            "mode": mode,
                            "application_id": str(app_id) if app_id else None,
                            "storage_space_id": str(space_id) if space_id else None,
                        },
                    )
                )
                await session.flush()
                run_id = run.id
                await session.commit()

                spaces = (
                    await session.scalars(
                        select(StorageSpaceModel).where(
                            StorageSpaceModel.tenant_id == tenant_id,
                            StorageSpaceModel.status == "active",
                        )
                    )
                ).all()
                if app_id:
                    spaces = [row for row in spaces if row.application_id == app_id]
                if space_id:
                    spaces = [row for row in spaces if row.id == space_id]
                allowed_space_ids = {row.id for row in spaces}
                files = (
                    await session.scalars(
                        select(FileObjectModel).where(
                            FileObjectModel.tenant_id == tenant_id,
                            FileObjectModel.status == "available",
                            FileObjectModel.storage_space_id.in_(
                                allowed_space_ids or {UUID(int=0)}
                            ),
                        )
                    )
                ).all()

                provider_objects: list[Any] = []
                token: str | None = None
                while True:
                    page, next_token = await self.object_storage.list_objects(
                        "", continuation_token=token, max_keys=1000
                    )
                    provider_objects.extend(page)
                    token = next_token
                    run.provider_cursor = token
                    run.attempt_count += 1
                    run.updated_at = datetime.now(UTC)
                    await session.commit()
                    if token is None:
                        break
                result = compare_inventory(
                    [
                        ReconciliationFile(
                            physical_key=row.object_key,
                            tenant_id=str(row.tenant_id),
                            application_id=str(row.application_id) if row.application_id else None,
                            storage_space_id=str(row.storage_space_id),
                            content_length=row.content_length,
                        )
                        for row in files
                    ],
                    [
                        ReconciliationObject(str(obj.key), int(obj.content_length))
                        for obj in provider_objects
                    ],
                    known_namespace_prefixes=tuple(
                        (
                            row.storage_namespace
                            or f"v1/tenants/{row.tenant_id}/spaces/{row.id}"
                        )
                        + "/"
                        for row in spaces
                    ),
                )
                counts: dict[str, int] = {}
                matched_files = {
                    item.physical_key
                    for item in result
                    if item.kind == ReconciliationDifference.MATCHED
                }
                for item in result:
                    counts[item.kind.value] = counts.get(item.kind.value, 0) + 1
                    if item.kind == ReconciliationDifference.MATCHED:
                        continue
                    session.add(
                        QuotaReconciliationDifferenceModel(
                            run_id=run.id,
                            tenant_id=tenant_id,
                            application_id=app_id,
                            storage_space_id=space_id,
                            kind=item.kind.value,
                            physical_key_fingerprint=_fingerprint(item.physical_key),
                            recorded_bytes=item.recorded_bytes,
                            observed_bytes=item.observed_bytes,
                            details={"mode": mode},
                        )
                    )
                if mode == "apply":
                    await self._apply_projection(
                        session,
                        tenant_id,
                        files,
                        matched_files,
                        run.id,
                        application_id=app_id,
                        storage_space_ids=allowed_space_ids,
                        scope_limited=app_id is not None or space_id is not None,
                    )
                run.status = "completed"
                run.summary = {
                    "counts": counts,
                    "matched_files": len(matched_files),
                    "provider_objects": len(provider_objects),
                }
                run.completed_at = datetime.now(UTC)
                session.add(
                    AuditEventModel(
                        tenant_id=tenant_id,
                        actor_principal_id=actor_id,
                        action="quota.reconciliation_completed",
                        resource_type="quota_reconciliation_run",
                        resource_id=str(run.id),
                        details={
                            "mode": mode,
                            "counts": counts,
                            "matched_files": len(matched_files),
                        },
                    )
                )
                await session.commit()
                return {"id": str(run.id), "mode": mode, "status": run.status, **run.summary}
            except Exception as exc:
                await session.rollback()
                if run is not None and run_id is not None:
                    failed = await session.get(QuotaReconciliationRunModel, run_id)
                    if failed is not None:
                        failed.status = "failed"
                        failed.error_code = type(exc).__name__[:64]
                        failed.error_message = str(exc)[:1024]
                        failed.completed_at = datetime.now(UTC)
                        failed.updated_at = datetime.now(UTC)
                        failed.summary = {"error": "provider_or_reconciliation_failure"}
                        session.add(
                            AuditEventModel(
                                tenant_id=tenant_id,
                                actor_principal_id=actor_id,
                                action="quota.reconciliation_failed",
                                resource_type="quota_reconciliation_run",
                                resource_id=str(run_id),
                                details={"error_code": failed.error_code},
                            )
                        )
                        await session.commit()
                raise
            finally:
                await session.execute(
                    select(func.pg_advisory_unlock(_tenant_lock_key(tenant_id)))
                )
                await session.commit()

    async def reconcile_internal(
        self,
        tenant_id: UUID,
        *,
        mode: str = "audit",
        application_id: str | None = None,
        storage_space_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Run the same service for a trusted scheduler, without user auth."""
        return await self.reconcile(
            None,
            mode=mode,
            application_id=application_id,
            storage_space_id=storage_space_id,
            idempotency_key=idempotency_key,
            internal_tenant_id=tenant_id,
        )

    async def get_run(
        self,
        context: PrincipalContext,
        run_id: str,
        difference_kind: ReconciliationDifference | None = None,
    ) -> dict[str, Any]:
        await self.authorizer.require_permission(context, "quotas.read")
        try:
            identifier = UUID(run_id)
        except ValueError as exc:
            raise ApiError(
                "resource_not_found", "Reconciliation run not found", status_code=404
            ) from exc
        async with self.session_factory() as session:
            run = await session.scalar(
                select(QuotaReconciliationRunModel).where(
                    QuotaReconciliationRunModel.tenant_id == context.tenant_id,
                    QuotaReconciliationRunModel.id == identifier,
                )
            )
            if run is None:
                raise ApiError(
                    "resource_not_found", "Reconciliation run not found", status_code=404
                )
            difference_stmt = select(QuotaReconciliationDifferenceModel).where(
                QuotaReconciliationDifferenceModel.run_id == run.id
            )
            if difference_kind is not None:
                difference_stmt = difference_stmt.where(
                    QuotaReconciliationDifferenceModel.kind == difference_kind.value
                )
            differences = (await session.scalars(difference_stmt)).all()
            return {
                "id": str(run.id),
                "mode": run.mode,
                "status": run.status,
                "summary": dict(run.summary or {}),
                "differences": [
                    {
                        "kind": row.kind,
                        "recorded_bytes": row.recorded_bytes,
                        "observed_bytes": row.observed_bytes,
                        "physical_key_fingerprint": row.physical_key_fingerprint,
                    }
                    for row in differences
                ],
            }

    async def _apply_projection(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        files: Sequence[Any],
        matched: set[str],
        run_id: UUID,
        *,
        application_id: UUID | None,
        storage_space_ids: set[UUID],
        scope_limited: bool,
    ) -> None:
        totals: dict[tuple[UUID | None, UUID | None], int] = {}
        for row in files:
            if row.object_key in matched:
                totals[(row.application_id, row.storage_space_id)] = (
                    totals.get((row.application_id, row.storage_space_id), 0) + row.content_length
                )
        quota_stmt = select(QuotaModel).where(QuotaModel.tenant_id == tenant_id)
        if scope_limited:
            predicates = []
            if application_id is not None:
                predicates.append(QuotaModel.application_id == application_id)
            if storage_space_ids:
                predicates.append(QuotaModel.storage_space_id.in_(storage_space_ids))
            quota_stmt = quota_stmt.where(or_(*predicates))
        quotas = (await session.scalars(quota_stmt.with_for_update())).all()
        for quota in quotas:
            if quota.application_id is not None:
                value = sum(
                    size for (app, _), size in totals.items() if app == quota.application_id
                )
            elif quota.storage_space_id is not None:
                value = totals.get((None, quota.storage_space_id), 0) + sum(
                    size for (app, space), size in totals.items() if space == quota.storage_space_id
                )
            else:
                value = sum(totals.values())
            quota.used_bytes = value
            quota.consistency_status = "reconciled"
            quota.measured_at = datetime.now(UTC)
            quota.last_reconciliation_run_id = run_id
            quota.drift_summary = {"source": "shared_s3_inventory", "used_bytes": value}


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tenant_lock_key(tenant_id: UUID) -> int:
    """Derive a stable signed PostgreSQL advisory-lock key from a tenant UUID."""
    return int.from_bytes(hashlib.sha256(tenant_id.bytes).digest()[:8], "big", signed=True)
