"""Explicit, resumable executor for already-reviewed provider migrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.files.infrastructure.ingestion_models import FileIngestionRecordModel
from s3mp.files.infrastructure.models import ProviderMigrationManifestModel
from s3mp.storage.domain.policy import ProviderTarget


class ProviderStorage(Protocol):
    async def head(self, target: ProviderTarget): ...
    async def copy(self, source: ProviderTarget, destination: ProviderTarget): ...
    async def delete(self, target: ProviderTarget) -> None: ...


@dataclass(frozen=True, slots=True)
class MigrationExecutionResult:
    migrated: int = 0
    quarantined: int = 0
    cleaned: int = 0


def _target(bucket: str | None, key: str | None) -> ProviderTarget | None:
    return ProviderTarget(bucket, key) if bucket and key else None


def _same_metadata(source: object, target: object) -> bool:
    return (
        getattr(source, "content_length", None) == getattr(target, "content_length", None)
        and getattr(source, "etag", None) == getattr(target, "etag", None)
    )


class ProviderMigrationExecutor:
    """Execute only reviewed manifests and retain the source until cleanup."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], storage: ProviderStorage) -> None:
        self._sf = session_factory
        self._storage = storage

    async def copy_verified(self, limit: int = 100) -> MigrationExecutionResult:
        migrated = quarantined = 0
        async with self._sf() as session:
            manifests = list((await session.scalars(
                select(ProviderMigrationManifestModel)
                .where(ProviderMigrationManifestModel.state == "ready_for_verified_copy")
                .order_by(ProviderMigrationManifestModel.created_at)
                .limit(limit)
            )).all())
        for manifest in manifests:
            source, target = _target(manifest.source_bucket, manifest.source_key), _target(manifest.target_bucket, manifest.target_key)
            if source is None or target is None or manifest.record_type != "ingestion":
                await self._set_state(manifest.id, "quarantined", "manifest_not_executable")
                quarantined += 1
                continue
            source_metadata = await self._storage.head(source)
            if source_metadata is None:
                await self._set_state(manifest.id, "quarantined", "source_object_missing")
                quarantined += 1
                continue
            target_metadata = await self._storage.head(target)
            if target_metadata is None:
                target_metadata = await self._storage.copy(source, target)
            if not _same_metadata(source_metadata, target_metadata):
                await self._set_state(manifest.id, "quarantined", "copy_verification_failed")
                quarantined += 1
                continue
            if not await self._promote_ingestion(manifest.id, target):
                await self._set_state(manifest.id, "quarantined", "record_changed_since_plan")
                quarantined += 1
                continue
            migrated += 1
        return MigrationExecutionResult(migrated=migrated, quarantined=quarantined)

    async def cleanup_verified_sources(self, limit: int = 100) -> MigrationExecutionResult:
        """Delete old objects only after a prior verified copy and explicit call."""
        cleaned = 0
        async with self._sf() as session:
            manifests = list((await session.scalars(
                select(ProviderMigrationManifestModel)
                .where(ProviderMigrationManifestModel.state == "copied_verified")
                .order_by(ProviderMigrationManifestModel.updated_at)
                .limit(limit)
            )).all())
        for manifest in manifests:
            source, target = _target(manifest.source_bucket, manifest.source_key), _target(manifest.target_bucket, manifest.target_key)
            if source is None or target is None:
                await self._set_state(manifest.id, "quarantined", "manifest_not_executable")
                continue
            target_metadata = await self._storage.head(target)
            if target_metadata is None:
                await self._set_state(manifest.id, "quarantined", "target_missing_before_cleanup")
                continue
            await self._storage.delete(source)
            await self._set_state(manifest.id, "cleanup_completed", None)
            cleaned += 1
        return MigrationExecutionResult(cleaned=cleaned)

    async def _promote_ingestion(self, manifest_id: UUID, target: ProviderTarget) -> bool:
        async with self._sf.begin() as session:
            manifest = await session.scalar(select(ProviderMigrationManifestModel).where(
                ProviderMigrationManifestModel.id == manifest_id
            ).with_for_update())
            if manifest is None or manifest.state != "ready_for_verified_copy":
                return False
            row = await session.scalar(select(FileIngestionRecordModel).where(
                FileIngestionRecordModel.tenant_id == manifest.tenant_id,
                FileIngestionRecordModel.id == manifest.record_id,
                FileIngestionRecordModel.provider_target_version == 0,
            ).with_for_update())
            if row is None:
                return False
            row.bucket, row.physical_key, row.provider_target_version = target.bucket, target.key, 1
            manifest.state, manifest.reason = "copied_verified", None
            return True

    async def _set_state(self, manifest_id: UUID, state: str, reason: str | None) -> None:
        async with self._sf.begin() as session:
            manifest = await session.scalar(select(ProviderMigrationManifestModel).where(
                ProviderMigrationManifestModel.id == manifest_id
            ).with_for_update())
            if manifest is not None:
                manifest.state, manifest.reason = state, reason
