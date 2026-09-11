"""Platform S3 batch manifests adapted from the vendored local-output contract."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from s3mp.knowledge.contracts import KnowledgeContract


class ExtractionOutputError(ValueError):
    """A candidate output cannot be stored as a platform knowledge batch."""


def source_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def deduplication_key(tenant_id: str, source_hash: str, contract_hash: str) -> str:
    """Stable logical key for successful tenant-scoped extraction deduplication."""
    if not tenant_id or len(source_hash) != 64 or len(contract_hash) != 64:
        raise ValueError("tenant and SHA-256 values are required for deduplication")
    return f"{tenant_id}:{source_hash}:{contract_hash}"


def build_source_manifest(
    *,
    task: dict[str, Any],
    batch_id: str,
    source_hash: str,
    size_bytes: int,
    contract: KnowledgeContract,
) -> dict[str, Any]:
    """Produce an S3MP-native manifest without local paths or file URIs."""
    source_file_id = task.get("source_file_id")
    if not isinstance(source_file_id, str) or not source_file_id:
        raise ExtractionOutputError("task source file id is required")
    return {
        "schemaVersion": "s3mp-knowledge-source-manifest-v1",
        "batchId": batch_id,
        "createdAt": datetime.now(UTC).isoformat(),
        "contract": {"version": contract.version, "manifestSha256": contract.manifest_hash},
        "source": {
            "sourceId": f"source::{source_hash[:16]}",
            "uri": f"s3mp://file/{source_file_id}",
            "tenantId": task["tenant_id"],
            "applicationId": task.get("source_application_id"),
            "logicalPath": task["source_object_key"],
            "storageSpaceId": task.get("source_storage_space_id"),
            "sha256": source_hash,
            "sizeBytes": size_bytes,
            "mediaType": task["source_content_type"],
        },
    }


def validate_platform_extraction_output(output: dict[str, Any]) -> None:
    """Validate the compatible report envelope while prohibiting local-only fields."""
    required = {
        "schemaVersion",
        "batch",
        "sources",
        "cards",
        "unresolved",
        "conflicts",
        "ontologyProposals",
        "validation",
    }
    missing = required.difference(output)
    if missing:
        raise ExtractionOutputError(
            f"extraction output missing fields: {', '.join(sorted(missing))}"
        )
    if output["schemaVersion"] != "2.0":
        raise ExtractionOutputError("unsupported extraction output schema version")
    sources = output["sources"]
    if not isinstance(sources, list) or not sources:
        raise ExtractionOutputError("extraction output requires at least one source")
    for source in sources:
        if not isinstance(source, dict) or not str(source.get("uri", "")).startswith(
            "s3mp://file/"
        ):
            raise ExtractionOutputError("source URI must be an S3MP file URI")
        if "localPath" in source or str(source.get("uri", "")).startswith("file://"):
            raise ExtractionOutputError("local source paths are forbidden in platform output")
