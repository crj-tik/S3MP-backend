"""Assess legacy retained rows before enabling trash migration.

This command is intentionally read-only.  Rows that cannot be mapped to a
tenant-owned storage namespace are reported as quarantined instead of being
rewritten automatically.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.files.infrastructure.models import FileObjectModel
from s3mp.storage.domain.policy import derive_provider_target
from s3mp.storage.infrastructure.models import StorageSpaceModel


async def assess() -> dict[str, Any]:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("database configuration is required")
    engine = create_engine(database_url)
    try:
        async with create_session_factory(engine)() as session:
            rows = await session.execute(
                select(FileObjectModel, StorageSpaceModel)
                .join(
                    StorageSpaceModel,
                    (StorageSpaceModel.tenant_id == FileObjectModel.tenant_id)
                    & (StorageSpaceModel.id == FileObjectModel.storage_space_id),
                )
                .where(FileObjectModel.soft_deleted.is_(True))
                .order_by(FileObjectModel.tenant_id, FileObjectModel.id)
            )
            candidates: list[dict[str, Any]] = []
            quarantined: list[dict[str, Any]] = []
            for file_obj, space in rows:
                item = {
                    "tenant_id": str(file_obj.tenant_id),
                    "file_id": str(file_obj.id),
                    "storage_space_id": str(file_obj.storage_space_id),
                    "object_key": file_obj.object_key,
                }
                prefix = space.storage_namespace or str(
                    derive_provider_target(
                        tenant_id=file_obj.tenant_id,
                        storage_space_id=file_obj.storage_space_id,
                        bucket=space.bucket,
                        relative_key="",
                        version=space.provider_target_version,
                    ).key
                ).rstrip("/")
                if not prefix or not file_obj.object_key.startswith(prefix + "/"):
                    item["reason"] = "physical_key_outside_storage_namespace"
                    quarantined.append(item)
                elif "/__trash__/" in file_obj.object_key:
                    item["reason"] = "already_in_trash_namespace_without_deletion_record"
                    quarantined.append(item)
                else:
                    item["original_relative_key"] = file_obj.object_key[len(prefix) + 1 :]
                    candidates.append(item)
            return {
                "mode": "read_only_assessment",
                "soft_deleted_rows": len(candidates) + len(quarantined),
                "candidates": candidates,
                "quarantined": quarantined,
            }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(assess())
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
