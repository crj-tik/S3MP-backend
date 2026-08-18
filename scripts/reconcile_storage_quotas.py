"""Audit and optionally reconcile tenant/application quota usage.

The default mode is read-only. ``--apply`` updates only ``used_bytes`` from
available, namespace-bound file rows; reservations are never rewritten by an
automated reconciliation run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from sqlalchemy import text

from s3mp.common.config import Settings, get_settings
from s3mp.common.database import create_engine


def _database_url() -> str | None:
    settings = get_settings()
    url = settings.secret_value("database_url")
    if url:
        return url
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deploy", ".env")
    if not os.path.isfile(env_path):
        return os.environ.get("S3MP_DOCKER_DATABASE_URL")
    loaded = Settings(_env_file=env_path)
    url = loaded.secret_value("database_url") or os.environ.get("S3MP_DOCKER_DATABASE_URL")
    if url:
        return url
    with open(env_path, encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("S3MP_DOCKER_DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return None


USAGE_QUERY = """
WITH available AS (
    SELECT f.tenant_id, f.application_id, COALESCE(SUM(f.content_length), 0) AS used_bytes
      FROM file_object AS f
      JOIN storage_space AS s
        ON s.tenant_id = f.tenant_id AND s.id = f.storage_space_id
      JOIN application AS a
        ON a.tenant_id = s.tenant_id AND a.id = s.application_id
     WHERE f.status = 'available'
       AND s.status = 'active'
       AND a.status = 'active'
       AND f.application_id IS NOT NULL
       AND f.storage_namespace IS NOT NULL
     GROUP BY f.tenant_id, f.application_id
), quota_usage AS (
    SELECT q.id, q.tenant_id, q.application_id, q.limit_bytes,
           q.used_bytes AS recorded_used_bytes,
           CASE WHEN q.application_id IS NULL
                THEN COALESCE((SELECT SUM(available.used_bytes)
                                FROM available
                               WHERE available.tenant_id = q.tenant_id), 0)
                ELSE COALESCE((SELECT available.used_bytes
                                 FROM available
                                WHERE available.tenant_id = q.tenant_id
                                  AND available.application_id = q.application_id), 0)
           END AS calculated_used_bytes
      FROM quota AS q
)
SELECT id, tenant_id, application_id, limit_bytes,
       recorded_used_bytes, calculated_used_bytes,
       (calculated_used_bytes > limit_bytes) AS exceeds_limit
  FROM quota_usage
 ORDER BY tenant_id, id
"""


async def reconcile(apply: bool) -> list[dict[str, Any]]:
    url = _database_url()
    if url and "@host.docker.internal:" in url:
        url = url.replace("@host.docker.internal:", "@localhost:")
    if not url:
        raise RuntimeError("database is not configured")
    engine = create_engine(url)
    try:
        async with engine.begin() as connection:
            rows = [dict(row) for row in (await connection.execute(text(USAGE_QUERY))).mappings()]
            for row in rows:
                row["usage_delta"] = int(row["calculated_used_bytes"]) - int(
                    row["recorded_used_bytes"]
                )
                row["calculated_available_bytes"] = max(
                    int(row["limit_bytes"]) - int(row["calculated_used_bytes"]), 0
                )
            if apply:
                for row in rows:
                    await connection.execute(
                        text("UPDATE quota SET used_bytes = :used WHERE id = :id"),
                        {"used": row["calculated_used_bytes"], "id": row["id"]},
                    )
        return rows
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile S3MP quota usage")
    parser.add_argument("--apply", action="store_true", help="write calculated used_bytes")
    args = parser.parse_args()
    rows = asyncio.run(reconcile(args.apply))
    print(json.dumps({"mode": "apply" if args.apply else "audit", "items": rows}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
