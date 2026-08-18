"""Run the shared-S3 inventory reconciler for active tenants.

This is an independent batch entry point so a full provider listing never
blocks realtime upload/delete work. It is read-only by default; ``--apply``
requires an explicit operator action and uses the same application service as
the protected HTTP management endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.governance.application.reconciliation_service import QuotaReconciliationService
from s3mp.storage.infrastructure.minio import MinioObjectStorageAdapter
from s3mp.tenant.infrastructure.models import TenantModel


def _ensure_models_loaded() -> None:
    """Load every FK target before the service flushes an audit/run record."""
    import s3mp.applications.infrastructure.models as _applications  # noqa: F401
    import s3mp.audit.infrastructure.models as _audit  # noqa: F401
    import s3mp.authorization.infrastructure.models as _authorization  # noqa: F401
    import s3mp.files.infrastructure.models as _files  # noqa: F401
    import s3mp.governance.infrastructure.models as _governance  # noqa: F401
    import s3mp.identity.infrastructure.models as _identity  # noqa: F401
    import s3mp.platform.infrastructure.models as _platform  # noqa: F401
    import s3mp.storage.infrastructure.models as _storage  # noqa: F401
    import s3mp.tenant.infrastructure.models as _tenant  # noqa: F401


async def run_once(
    *, apply: bool, limit: int, tenant_id: UUID | None = None
) -> list[dict[str, object]]:
    _ensure_models_loaded()
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url or not settings.s3_endpoint:
        raise RuntimeError("shared-S3 reconciliation requires database and object storage")
    engine = create_engine(database_url)
    try:
        sessions = create_session_factory(engine)
        async with sessions() as session:
            tenant_stmt = select(TenantModel.id).where(TenantModel.status == "active")
            if tenant_id is not None:
                tenant_stmt = tenant_stmt.where(TenantModel.id == tenant_id)
            tenant_ids = (
                await session.scalars(tenant_stmt.order_by(TenantModel.id).limit(limit))
            ).all()
        service = QuotaReconciliationService(
            sessions, MinioObjectStorageAdapter(settings), authorizer=None
        )
        return [
            await service.reconcile_internal(tenant_id, mode="apply" if apply else "audit")
            for tenant_id in tenant_ids
        ]
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile shared S3 inventory by tenant")
    parser.add_argument("--apply", action="store_true", help="apply matched usage projections")
    parser.add_argument("--limit", type=int, default=100, help="maximum active tenants per batch")
    parser.add_argument("--tenant-id", type=UUID, help="reconcile one exact active tenant")
    args = parser.parse_args()
    results = asyncio.run(
        run_once(
            apply=args.apply,
            limit=max(1, min(args.limit, 1000)),
            tenant_id=args.tenant_id,
        )
    )
    print({"mode": "apply" if args.apply else "audit", "tenants": results})


if __name__ == "__main__":
    main()
