"""Fail deployment when strict auth/worker safety invariants are not satisfied."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine

INVARIANT_SQL = text(
    """
    SELECT
      count(*) FILTER (WHERE p.id IS NULL OR p.type <> 'application' OR NOT p.enabled)
        AS invalid_application_principals,
      count(*) FILTER (WHERE a.status = 'active' AND NOT EXISTS (
        SELECT 1 FROM application_owner ao
        JOIN principal owner ON owner.tenant_id = ao.tenant_id
          AND owner.id = ao.owner_principal_id
        WHERE ao.tenant_id = a.tenant_id AND ao.application_id = a.id
          AND owner.enabled AND owner.type IN ('user', 'group')
      )) AS active_applications_without_owner,
      count(*) FILTER (WHERE a.status = 'active' AND EXISTS (
        SELECT 1 FROM api_key k WHERE k.tenant_id = a.tenant_id
          AND k.application_id = a.id AND k.status = 'active'
      ) AND (p.id IS NULL OR p.type <> 'application' OR NOT p.enabled))
        AS active_keys_without_valid_principal
    FROM application a
    LEFT JOIN principal p ON p.tenant_id = a.tenant_id AND p.id = a.principal_id
    """
)


async def check() -> dict[str, int]:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("database is not configured")
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            row = (await connection.execute(INVARIANT_SQL)).mappings().one()
            return {key: int(value or 0) for key, value in row.items()}
    finally:
        await engine.dispose()


def main() -> int:
    report = asyncio.run(check())
    print("security invariant report: " + ", ".join(f"{k}={v}" for k, v in report.items()))
    return 1 if any(report.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
