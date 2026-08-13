"""Plan legacy provider-key migration without exposing object locations.

Default mode is read-only.  ``--record-manifests`` only persists the reviewed
plan; it still does not copy, rewrite, or delete any provider object.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.files.application.provider_migration import ProviderMigrationPlan, classify_legacy_target
from s3mp.files.application.provider_migration_executor import ProviderMigrationExecutor
from s3mp.files.infrastructure.ingestion_models import FileIngestionRecordModel
from s3mp.files.infrastructure.models import (
    FileObjectModel, FileOperationModel, MultipartSessionModel,
    ProviderMigrationManifestModel, UploadSessionModel,
)
from s3mp.storage.infrastructure.models import StorageSpaceModel
from s3mp.storage.infrastructure.minio import MinioObjectStorageAdapter
# Load the referenced table into SQLAlchemy metadata before flushing a manifest.
from s3mp.tenant.infrastructure import models as _tenant_models  # noqa: F401


async def _spaces(session: Any) -> tuple[dict[UUID, dict[str, Any]], set[UUID]]:
    rows = (await session.scalars(select(StorageSpaceModel))).all()
    spaces = {row.id: {"id": str(row.id), "tenant_id": str(row.tenant_id), "bucket": row.bucket, "root_prefix": row.root_prefix} for row in rows}
    grouped: dict[tuple[str, str], set[UUID]] = {}
    for row in rows:
        grouped.setdefault((row.bucket, row.root_prefix or ""), set()).add(row.id)
    return spaces, {space_id for group in grouped.values() if len(group) > 1 for space_id in group}


async def plan(session_factory: async_sessionmaker[Any]) -> list[ProviderMigrationPlan]:
    async with session_factory() as session:
        spaces, overlaps = await _spaces(session)
        plans: list[ProviderMigrationPlan] = []

        async def append_rows(model: Any, record_type: str, *, ingestion: bool = False) -> None:
            for row in (await session.scalars(select(model).where(model.provider_target_version == 0))).all():
                source_key = row.physical_key if ingestion else row.object_key
                relative = row.relative_key if ingestion else None
                source_bucket = row.bucket if ingestion else None
                plans.append(classify_legacy_target(
                    record_type=record_type, record_id=row.id, tenant_id=row.tenant_id,
                    storage_space=spaces.get(row.storage_space_id), source_bucket=source_bucket,
                    source_key=source_key, relative_key=relative, overlapping_space_ids=overlaps,
                ))

        await append_rows(FileObjectModel, "file_object")
        await append_rows(UploadSessionModel, "upload_session")
        await append_rows(MultipartSessionModel, "multipart_session")
        await append_rows(FileIngestionRecordModel, "ingestion", ingestion=True)
        for row in (await session.scalars(select(FileOperationModel).where(FileOperationModel.provider_target_version == 0))).all():
            plans.append(classify_legacy_target(
                record_type="file_operation", record_id=row.id, tenant_id=row.tenant_id,
                storage_space=spaces.get(row.storage_space_id) if row.storage_space_id else None,
                source_bucket=None, source_key=None, relative_key=None,
                overlapping_space_ids=overlaps,
            ))
        return plans


async def record_manifests(session_factory: async_sessionmaker[Any], plans: list[ProviderMigrationPlan]) -> None:
    async with session_factory.begin() as session:
        for item in plans:
            existing = await session.scalar(select(ProviderMigrationManifestModel).where(
                ProviderMigrationManifestModel.tenant_id == item.tenant_id,
                ProviderMigrationManifestModel.record_type == item.record_type,
                ProviderMigrationManifestModel.record_id == item.record_id,
            ))
            if existing is None:
                session.add(ProviderMigrationManifestModel(
                    tenant_id=item.tenant_id, storage_space_id=item.storage_space_id,
                    record_type=item.record_type, record_id=item.record_id, state=item.state,
                    source_bucket=item.source_bucket, source_key=item.source_key,
                    target_bucket=item.target_bucket, target_key=item.target_key,
                    source_fingerprint=item.source_fingerprint, target_fingerprint=item.target_fingerprint,
                    reason=item.reason,
                ))


async def run(*, persist: bool = False) -> dict[str, Any]:
    database_url = get_settings().secret_value("database_url")
    if not database_url:
        raise RuntimeError("provider target migration requires database configuration")
    engine = create_engine(database_url)
    try:
        plans = await plan(create_session_factory(engine))
        if persist:
            await record_manifests(create_session_factory(engine), plans)
        states = Counter(item.state for item in plans)
        reasons = Counter(item.reason for item in plans)
        return {"mode": "manifest_recorded" if persist else "dry_run", "records": len(plans), "states": dict(sorted(states.items())), "reasons": dict(sorted(reasons.items()))}
    finally:
        await engine.dispose()


async def execute(*, cleanup: bool = False, limit: int = 100) -> dict[str, int]:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("provider target migration requires database configuration")
    engine = create_engine(database_url)
    try:
        executor = ProviderMigrationExecutor(
            create_session_factory(engine), MinioObjectStorageAdapter(settings)
        )
        result = await (executor.cleanup_verified_sources(limit) if cleanup else executor.copy_verified(limit))
        return {"migrated": result.migrated, "quarantined": result.quarantined, "cleaned": result.cleaned}
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan legacy provider-target migration")
    parser.add_argument("--record-manifests", action="store_true", help="persist plans only; never moves provider objects")
    parser.add_argument("--apply-verified-copy", action="store_true", help="copy only reviewed executable manifests and retain old objects")
    parser.add_argument("--cleanup-verified-sources", action="store_true", help="delete old objects only after a verified copy")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.apply_verified_copy and args.cleanup_verified_sources:
        parser.error("copy and cleanup are separate phases")
    if args.apply_verified_copy or args.cleanup_verified_sources:
        print(json.dumps(asyncio.run(execute(cleanup=args.cleanup_verified_sources, limit=args.limit)), sort_keys=True))
        return
    print(json.dumps(asyncio.run(run(persist=args.record_manifests)), sort_keys=True))


if __name__ == "__main__":
    main()
