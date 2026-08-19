"""Read-only audit of quota rows before enabling tenant/application allocation."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import func, select

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.governance.infrastructure.models import QuotaModel, QuotaReservationModel


async def audit() -> dict[str, object]:
    settings = get_settings()
    url = settings.secret_value("database_url")
    if not url:
        raise RuntimeError("S3MP_DATABASE_URL is required")
    engine = create_engine(url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            rows = list((await session.scalars(select(QuotaModel))).all())
            active_reservations = int(
                await session.scalar(
                    select(func.count(QuotaReservationModel.id)).where(
                        QuotaReservationModel.status == "reserved"
                    )
                )
                or 0
            )
        return {
            "total_quotas": len(rows),
            "tenant_totals": sum(
                1 for row in rows if row.application_id is None and row.storage_space_id is None
            ),
            "application_allocations": sum(1 for row in rows if row.application_id is not None),
            "legacy_storage_space_quotas": sum(
                1 for row in rows if row.storage_space_id is not None
            ),
            "active_reservations": active_reservations,
            "unsafe_rows": [
                {
                    "id": str(row.id),
                    "tenant_id": str(row.tenant_id),
                    "application_id": str(row.application_id) if row.application_id else None,
                    "storage_space_id": str(row.storage_space_id) if row.storage_space_id else None,
                    "used_bytes": row.used_bytes,
                    "reserved_bytes": row.reserved_bytes,
                }
                for row in rows
                if row.storage_space_id is not None and (row.used_bytes or row.reserved_bytes)
            ],
        }
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(audit()), ensure_ascii=False, indent=2))
