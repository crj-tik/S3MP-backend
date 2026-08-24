"""Quarantine ambiguous application storage before the implicit-storage migration."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import uuid4

from sqlalchemy import text

from audit_shared_s3_namespace import _database_url
from s3mp.common.database import create_engine

CONFLICTS = """
WITH conflicted_namespaces AS (
    SELECT storage_namespace
      FROM storage_space
     WHERE storage_namespace IS NOT NULL
     GROUP BY storage_namespace HAVING COUNT(*) > 1
), conflicted_apps AS (
    SELECT a.id AS application_id, a.tenant_id, 'namespace_mismatch' AS reason
      FROM application AS a
      JOIN storage_space AS s ON s.application_id = a.id
     WHERE s.tenant_id <> a.tenant_id
        OR s.storage_namespace IS DISTINCT FROM a.storage_namespace
    UNION
    SELECT s.application_id, s.tenant_id, 'duplicate_namespace'
      FROM storage_space AS s
     WHERE s.storage_namespace IN (SELECT storage_namespace FROM conflicted_namespaces)
)
SELECT application_id, tenant_id, reason FROM conflicted_apps
ORDER BY tenant_id, application_id
"""


async def reconcile(*, apply_isolation: bool) -> list[dict[str, str]]:
    database_url = _database_url()
    if database_url and "@host.docker.internal:" in database_url:
        database_url = database_url.replace("@host.docker.internal:", "@localhost:")
    if not database_url:
        raise RuntimeError("database is not configured")
    engine = create_engine(database_url)
    try:
        async with engine.begin() as connection:
            rows = (await connection.execute(text(CONFLICTS))).mappings().all()
            report = [
                {key: str(value) for key, value in row.items()} for row in rows
            ]
            if not apply_isolation:
                return report
            for row in rows:
                await connection.execute(
                    text(
                        "UPDATE application SET status = 'pending_takeover', "
                        "authorization_version = authorization_version + 1 "
                        "WHERE tenant_id = :tenant_id AND id = :application_id "
                        "AND status = 'active'"
                    ),
                    row,
                )
                await connection.execute(
                    text(
                        "UPDATE storage_space SET status = 'suspended' "
                        "WHERE tenant_id = :tenant_id AND application_id = :application_id "
                        "AND status = 'active'"
                    ),
                    row,
                )
                await connection.execute(
                    text(
                        """
                        INSERT INTO audit_event
                            (id, tenant_id, actor_principal_id, action, resource_type,
                             resource_id, details)
                        VALUES
                            (:id, :tenant_id, NULL, 'application.storage_quarantined',
                             'application', :resource_id, CAST(:details AS json))
                        """
                    ),
                    {
                        "id": uuid4(),
                        "tenant_id": row["tenant_id"],
                        "resource_id": str(row["application_id"]),
                        "details": json.dumps(
                            {"reason_code": row["reason"]}, separators=(",", ":")
                        ),
                    },
                )
            return report
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply-isolation",
        action="store_true",
        help="Suspend conflicted spaces and contain their applications.",
    )
    args = parser.parse_args()
    report = asyncio.run(reconcile(apply_isolation=args.apply_isolation))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report and not args.apply_isolation else 0


if __name__ == "__main__":
    raise SystemExit(main())
