"""Read-only pre-rollout security inventory for tenant and provider boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import text

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine


def _fingerprint(*values: object) -> str:
    payload = "\x1f".join(str(value) for value in values)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


async def inventory() -> dict[str, Any]:
    """Return only aggregate counts and redacted conflict identifiers."""
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("security audit requires database configuration")
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            overlaps: Sequence[Any] = (
                await connection.execute(
                    text(
                        "SELECT bucket, root_prefix FROM storage_space "
                        "GROUP BY bucket, root_prefix HAVING COUNT(DISTINCT tenant_id) > 1"
                    )
                )
            ).all()
            unscoped_files = await connection.scalar(
                text("SELECT COUNT(*) FROM file_object WHERE object_key NOT LIKE 'v1/tenants/%/spaces/%/%'")
            )
            unscoped_uploads = await connection.scalar(
                text("SELECT COUNT(*) FROM upload_session WHERE object_key NOT LIKE 'v1/tenants/%/spaces/%/%'")
            )
            unscoped_multipart = await connection.scalar(
                text("SELECT COUNT(*) FROM multipart_session WHERE object_key NOT LIKE 'v1/tenants/%/spaces/%/%'")
            )
            unsafe_operations = await connection.scalar(
                text(
                    "SELECT COUNT(*) FROM file_operation "
                    "WHERE status IN ('pending', 'running', 'retry_wait') "
                    "AND (storage_space_id IS NULL OR authorization_evidence IS NULL)"
                )
            )
            orphaned_apps = await connection.scalar(
                text(
                    "SELECT COUNT(*) FROM application a WHERE a.status = 'active' AND NOT EXISTS ("
                    "SELECT 1 FROM application_owner o JOIN membership m "
                    "ON m.tenant_id = o.tenant_id AND m.principal_id = o.owner_principal_id "
                    "WHERE o.tenant_id = a.tenant_id AND o.application_id = a.id "
                    "AND m.status = 'active' AND (m.expires_at IS NULL OR m.expires_at > CURRENT_TIMESTAMP))"
                )
            )
            expired_bindings = await connection.scalar(
                text("SELECT COUNT(*) FROM role_binding WHERE expires_at <= CURRENT_TIMESTAMP")
            )
    finally:
        await engine.dispose()
    return {
        "storage_namespace_overlap_count": len(overlaps),
        "storage_namespace_overlap_ids": sorted(_fingerprint(row[0], row[1]) for row in overlaps),
        "legacy_unscoped_file_count": int(unscoped_files or 0),
        "legacy_unscoped_upload_count": int(unscoped_uploads or 0),
        "legacy_unscoped_multipart_count": int(unscoped_multipart or 0),
        "unsafe_durable_operation_count": int(unsafe_operations or 0),
        "active_application_without_active_owner_count": int(orphaned_apps or 0),
        "expired_role_binding_count": int(expired_bindings or 0),
    }


def main() -> None:
    print(json.dumps(asyncio.run(inventory()), sort_keys=True))


if __name__ == "__main__":
    main()
