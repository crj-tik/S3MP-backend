"""Pure matching and aggregation primitives for shared-S3 quota reconciliation."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class ReconciliationDifference(StrEnum):
    MATCHED = "matched"
    PROVIDER_MISSING = "provider_missing"
    DB_MISSING = "db_missing"
    SIZE_MISMATCH = "size_mismatch"
    DUPLICATE_MAPPING = "duplicate_mapping"
    ORPHAN_OBJECT = "orphan_object"


@dataclass(frozen=True, slots=True)
class ReconciliationFile:
    physical_key: str
    tenant_id: str
    application_id: str | None
    storage_space_id: str
    content_length: int
    active: bool = True


@dataclass(frozen=True, slots=True)
class ReconciliationObject:
    physical_key: str
    content_length: int


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    kind: ReconciliationDifference
    physical_key: str
    recorded_bytes: int | None = None
    observed_bytes: int | None = None


def compare_inventory(
    files: Iterable[ReconciliationFile],
    objects: Iterable[ReconciliationObject],
    *,
    known_namespace_prefixes: Iterable[str] = (),
) -> list[ReconciliationResult]:
    """Compare active DB projections with a server-scoped provider inventory."""
    file_rows: dict[str, list[ReconciliationFile]] = {}
    for row in files:
        file_rows.setdefault(row.physical_key, []).append(row)
    provider_rows = {row.physical_key: row for row in objects}
    results: list[ReconciliationResult] = []

    for key, rows in file_rows.items():
        if len(rows) > 1:
            results.append(ReconciliationResult(ReconciliationDifference.DUPLICATE_MAPPING, key))
            continue
        row = rows[0]
        provider = provider_rows.pop(key, None)
        if not row.active:
            continue
        if provider is None:
            results.append(
                ReconciliationResult(
                    ReconciliationDifference.PROVIDER_MISSING,
                    key,
                    recorded_bytes=row.content_length,
                )
            )
        elif provider.content_length != row.content_length:
            results.append(
                ReconciliationResult(
                    ReconciliationDifference.SIZE_MISMATCH,
                    key,
                    recorded_bytes=row.content_length,
                    observed_bytes=provider.content_length,
                )
            )
        else:
            results.append(
                ReconciliationResult(
                    ReconciliationDifference.MATCHED,
                    key,
                    recorded_bytes=row.content_length,
                    observed_bytes=provider.content_length,
                )
            )

    prefixes = tuple(known_namespace_prefixes)
    for key, provider_obj in provider_rows.items():
        kind = (
            ReconciliationDifference.DB_MISSING
            if any(key.startswith(prefix) for prefix in prefixes)
            else ReconciliationDifference.ORPHAN_OBJECT
        )
        results.append(
            ReconciliationResult(kind, key, observed_bytes=provider_obj.content_length)
        )
    return results
