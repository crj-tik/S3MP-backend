"""Read-only audit for the shared S3 tenant/application namespace migration."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from sqlalchemy import text

from s3mp.common.config import Settings, get_settings
from s3mp.common.database import create_engine

QUERIES: dict[str, str] = {
    "storage_spaces_without_application": """
        SELECT id, tenant_id, name
        FROM storage_space
        WHERE application_id IS NULL OR storage_namespace IS NULL
        ORDER BY tenant_id, id
    """,
    "duplicate_application_spaces": """
        SELECT tenant_id, application_id, COUNT(*) AS count
        FROM storage_space
        WHERE application_id IS NOT NULL
        GROUP BY tenant_id, application_id
        HAVING COUNT(*) > 1
        ORDER BY tenant_id, application_id
    """,
    "duplicate_namespaces": """
        SELECT storage_namespace, COUNT(*) AS count
        FROM storage_space
        WHERE storage_namespace IS NOT NULL
        GROUP BY storage_namespace
        HAVING COUNT(*) > 1
        ORDER BY storage_namespace
    """,
    "overlapping_legacy_prefixes": """
        SELECT a.tenant_id, a.id AS left_space_id, b.id AS right_space_id,
               a.root_prefix AS left_prefix, b.root_prefix AS right_prefix
        FROM storage_space AS a
        JOIN storage_space AS b
          ON a.tenant_id = b.tenant_id AND a.id < b.id
        WHERE a.root_prefix <> '' AND b.root_prefix <> ''
          AND (a.root_prefix = b.root_prefix
               OR a.root_prefix LIKE b.root_prefix || '/%'
               OR b.root_prefix LIKE a.root_prefix || '/%')
        ORDER BY a.tenant_id, a.id, b.id
    """,
    "invalid_legacy_prefixes": """
        SELECT id, tenant_id, root_prefix
        FROM storage_space
        WHERE root_prefix ~ '(^/|\\\\|%|(^|/)(\\.|\\.\\.)(/|$)|//)'
        ORDER BY tenant_id, id
    """,
    "orphan_file_storage_spaces": """
        SELECT f.id, f.tenant_id, f.storage_space_id
        FROM file_object AS f
        LEFT JOIN storage_space AS s
          ON s.tenant_id = f.tenant_id AND s.id = f.storage_space_id
        WHERE s.id IS NULL
        ORDER BY f.tenant_id, f.id
    """,
    "legacy_file_targets": """
        SELECT 'file_object' AS record_type, COUNT(*) AS count
        FROM file_object WHERE provider_target_version = 0
        UNION ALL
        SELECT 'upload_session', COUNT(*) FROM upload_session WHERE provider_target_version = 0
        UNION ALL
        SELECT 'multipart_session', COUNT(*)
        FROM multipart_session WHERE provider_target_version = 0
        UNION ALL
        SELECT 'file_operation', COUNT(*) FROM file_operation WHERE provider_target_version = 0
        UNION ALL
        SELECT 'file_ingestion_record', COUNT(*)
        FROM file_ingestion_record WHERE provider_target_version = 0
    """,
    "migration_manifests_needing_review": """
        SELECT state, COUNT(*) AS count
        FROM provider_migration_manifest
        WHERE state IN ('pending_review', 'quarantined')
        GROUP BY state
        ORDER BY state
    """,
}


def _database_url() -> str | None:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if database_url:
        return database_url
    local_env = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deploy", ".env")
    if not os.path.isfile(local_env):
        return os.environ.get("S3MP_DOCKER_DATABASE_URL")
    settings = Settings(_env_file=local_env)
    database_url = settings.secret_value("database_url") or os.environ.get(
        "S3MP_DOCKER_DATABASE_URL"
    )
    if database_url:
        return database_url
    with open(local_env, encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("S3MP_DOCKER_DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return None


async def audit() -> dict[str, list[dict[str, Any]]]:
    database_url = _database_url()
    if database_url and "@host.docker.internal:" in database_url:
        database_url = database_url.replace("@host.docker.internal:", "@localhost:")
    if not database_url:
        raise RuntimeError("database is not configured")
    engine = create_engine(database_url)
    try:
        result: dict[str, list[dict[str, Any]]] = {}
        async with engine.connect() as connection:
            for name, query in QUERIES.items():
                rows = (await connection.execute(text(query))).mappings().all()
                result[name] = [dict(row) for row in rows]
        return result
    finally:
        await engine.dispose()


def main() -> int:
    print(json.dumps(asyncio.run(audit()), ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
