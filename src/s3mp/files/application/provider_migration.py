"""Safe classification primitives for legacy provider-target migration.

The planner intentionally never calls object storage.  It can be used for a
read-only dry-run and for producing durable, operator-reviewed manifests before
any separate copy phase is approved.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from s3mp.storage.domain.policy import StoragePolicyError, derive_provider_target


@dataclass(frozen=True, slots=True)
class ProviderMigrationPlan:
    record_type: str
    record_id: UUID
    tenant_id: UUID
    storage_space_id: UUID | None
    state: str
    reason: str
    source_bucket: str | None
    source_key: str | None
    target_bucket: str | None
    target_key: str | None
    source_fingerprint: str
    target_fingerprint: str | None


def fingerprint(*values: object) -> str:
    """Return a stable redacted identifier; never expose provider locations."""
    return hashlib.sha256("\x1f".join(str(value) for value in values).encode()).hexdigest()[:32]


def classify_legacy_target(
    *,
    record_type: str,
    record_id: UUID,
    tenant_id: UUID,
    storage_space: dict[str, Any] | None,
    source_bucket: str | None,
    source_key: str | None,
    relative_key: str | None,
    overlapping_space_ids: set[UUID],
) -> ProviderMigrationPlan:
    """Classify one legacy record without assuming its provider key is safe.

    Only ingestion records preserve both a canonical relative key and source
    bucket, so other historical file/session records are deliberately held for
    manual mapping instead of guessing from their old physical key.
    """
    source = fingerprint(source_bucket or "", source_key or "")
    if storage_space is None:
        return ProviderMigrationPlan(record_type, record_id, tenant_id, None, "quarantined", "storage_space_missing", source_bucket, source_key, None, None, source, None)
    space_id = UUID(str(storage_space["id"]))
    if space_id in overlapping_space_ids:
        return ProviderMigrationPlan(record_type, record_id, tenant_id, space_id, "quarantined", "overlapping_legacy_root", source_bucket, source_key, None, None, source, None)
    if not relative_key:
        return ProviderMigrationPlan(record_type, record_id, tenant_id, space_id, "pending_review", "relative_key_not_proven", source_bucket, source_key, None, None, source, None)
    if source_bucket is not None and source_bucket != str(storage_space["bucket"]):
        return ProviderMigrationPlan(record_type, record_id, tenant_id, space_id, "quarantined", "source_bucket_mismatch", source_bucket, source_key, None, None, source, None)
    try:
        target = derive_provider_target(
            tenant_id=tenant_id,
            storage_space_id=space_id,
            bucket=str(storage_space["bucket"]),
            relative_key=relative_key,
            operator_prefix=str(storage_space.get("root_prefix") or ""),
            version=1,
        )
    except (KeyError, TypeError, ValueError, StoragePolicyError):
        return ProviderMigrationPlan(record_type, record_id, tenant_id, space_id, "quarantined", "relative_key_invalid", source_bucket, source_key, None, None, source, None)
    return ProviderMigrationPlan(
        record_type, record_id, tenant_id, space_id, "ready_for_verified_copy",
        "verified_mapping_required", source_bucket, source_key, target.bucket, target.key,
        source, fingerprint(target.bucket, target.key),
    )
