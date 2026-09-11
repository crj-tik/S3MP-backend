"""Backfill deterministic public file references for legacy file records.

The command is read-only by default.  Use ``--apply`` to persist the server-
computed SHA-256 and ``public_file_ref`` values.  A failed record is reported
and can be retried by running the command again; legacy UUID addressing remains
available until a record is successfully backfilled.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.common.config import Settings, get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.files.application.file_ref_backfill import (
    application_id_for_file,
    relative_key_for_file,
)
from s3mp.files.domain.file_reference import generate_file_ref
from s3mp.files.infrastructure.models import FileObjectModel
from s3mp.storage.domain.policy import ProviderTarget
from s3mp.storage.infrastructure.minio import (
    MinioObjectStorageAdapter,
    ObjectStorageUnavailable,
)
from s3mp.storage.infrastructure.models import StorageSpaceModel

logger = logging.getLogger(__name__)


@dataclass
class BackfillReport:
    scanned: int = 0
    eligible: int = 0
    updated: int = 0
    would_update: int = 0
    skipped: int = 0
    failed: int = 0
    reasons: Counter[str] = field(default_factory=Counter)

    def skip(self, reason: str) -> None:
        self.skipped += 1
        self.reasons[reason] += 1

    def fail(self, reason: str) -> None:
        self.failed += 1
        self.reasons[reason] += 1

    def as_dict(self, *, mode: str) -> dict[str, Any]:
        return {
            "mode": mode,
            "scanned": self.scanned,
            "eligible": self.eligible,
            "updated": self.updated,
            "would_update": self.would_update,
            "skipped": self.skipped,
            "failed": self.failed,
            "reasons": dict(sorted(self.reasons.items())),
        }


def _settings() -> Settings:
    """Load deploy/.env when running the migration outside the API process."""
    env_file = Path(__file__).resolve().parents[1] / "deploy" / ".env"
    return Settings(_env_file=env_file) if env_file.is_file() else get_settings()


async def _candidates(
    session_factory: async_sessionmaker[AsyncSession], limit: int
) -> list[tuple[FileObjectModel, StorageSpaceModel]]:
    async with session_factory() as session:
        result = await session.execute(
            select(FileObjectModel, StorageSpaceModel)
            .join(
                StorageSpaceModel,
                (StorageSpaceModel.tenant_id == FileObjectModel.tenant_id)
                & (StorageSpaceModel.id == FileObjectModel.storage_space_id),
            )
            .where(
                FileObjectModel.public_file_ref.is_(None),
                FileObjectModel.status == "available",
                FileObjectModel.soft_deleted.is_(False),
            )
            .order_by(FileObjectModel.tenant_id, FileObjectModel.id)
            .limit(limit)
        )
        return list(result.all())


async def _persist(
    session_factory: async_sessionmaker[AsyncSession],
    file_id: UUID,
    file_ref: str,
    checksum: str,
) -> str:
    """Persist a result only if the row is still unreferenced and collision-free."""
    async with session_factory.begin() as session:
        row = await session.scalar(
            select(FileObjectModel)
            .where(FileObjectModel.id == file_id)
            .with_for_update()
        )
        if row is None:
            return "row_missing"
        if row.public_file_ref is not None:
            return "already_backfilled"
        collision = await session.scalar(
            select(FileObjectModel.id).where(
                FileObjectModel.public_file_ref == file_ref,
                FileObjectModel.id != file_id,
            )
        )
        if collision is not None:
            return "file_ref_collision"
        row.checksum = checksum
        row.public_file_ref = file_ref
        await session.flush()
        return "updated"


async def backfill(*, apply: bool, limit: int) -> dict[str, Any]:
    settings = _settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("database configuration is required")
    if not settings.s3_endpoint or not settings.s3_bucket:
        raise RuntimeError("S3 endpoint and bucket configuration are required")

    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    storage = MinioObjectStorageAdapter(settings)
    report = BackfillReport()
    try:
        for file_obj, space in await _candidates(session_factory, limit):
            report.scanned += 1
            try:
                relative_key = relative_key_for_file(file_obj, space)
                application_id = application_id_for_file(file_obj, space)
                target = ProviderTarget(bucket=space.bucket, key=file_obj.object_key)
                before = await storage.head(target)
                if before is None:
                    report.skip("provider_object_not_found")
                    continue
                if before.content_length != file_obj.content_length:
                    report.skip("content_length_mismatch")
                    continue

                report.eligible += 1
                checksum = await storage.hash_sha256(target)
                after = await storage.head(target)
                if after is None:
                    report.skip("provider_object_removed_during_hash")
                    continue
                if after.content_length != file_obj.content_length:
                    report.skip("content_length_changed_during_hash")
                    continue
                if before.etag and after.etag and before.etag != after.etag:
                    report.skip("provider_object_changed_during_hash")
                    continue

                file_ref = generate_file_ref(
                    tenant_id=file_obj.tenant_id,
                    application_id=application_id,
                    relative_key=relative_key,
                    metadata=file_obj.metadata_json,
                    checksum=checksum,
                )
                if file_ref is None:
                    report.skip("file_ref_generation_failed")
                    continue
                if not apply:
                    report.would_update += 1
                    continue

                persisted = await _persist(session_factory, file_obj.id, file_ref, checksum)
                if persisted == "updated":
                    report.updated += 1
                else:
                    report.skip(persisted)
            except (ObjectStorageUnavailable, ValueError) as exc:
                reason = str(exc) or exc.__class__.__name__
                report.fail(reason)
                logger.warning(
                    "file_ref_backfill_failed",
                    extra={"file_id": str(file_obj.id), "reason": reason},
                )
            except Exception:
                report.fail("unexpected_error")
                logger.exception(
                    "file_ref_backfill_unexpected_error",
                    extra={"file_id": str(file_obj.id)},
                )
        return report.as_dict(mode="apply" if apply else "dry_run")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill server-computed file_ref values")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="persist server-computed checksum and file_ref values; default is read-only",
    )
    parser.add_argument("--limit", type=int, default=100, help="maximum records to inspect")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    print(json.dumps(asyncio.run(backfill(apply=args.apply, limit=args.limit)), ensure_ascii=False))


if __name__ == "__main__":
    main()
