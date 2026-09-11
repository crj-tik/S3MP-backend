"""Deterministic, completion-marker-based S3 knowledge batch writer."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from s3mp.knowledge.application.batch_manifest import build_source_manifest
from s3mp.knowledge.application.prompting import ValidatedDraft
from s3mp.knowledge.contracts import KnowledgeContract
from s3mp.storage.domain.policy import ProviderTarget

logger = logging.getLogger(__name__)


class BatchWriteError(RuntimeError):
    """A batch object could not be written and verified."""


class KnowledgeObjectStorage(Protocol):
    async def put(self, target: ProviderTarget, body: bytes, content_type: str) -> Any: ...

    async def head(self, target: ProviderTarget) -> Any: ...


class S3KnowledgeBatchWriter:
    def __init__(self, storage: KnowledgeObjectStorage, *, bucket: str) -> None:
        self._storage, self._bucket = storage, bucket

    async def write(
        self,
        *,
        task: dict[str, Any],
        source_body: bytes,
        drafts: tuple[ValidatedDraft, ...],
        contract: KnowledgeContract,
        report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tenant_id = str(task["tenant_id"])
        batch_id = f"batch-{task['id']}"
        prefix = f"tenants/{tenant_id}/knowledge-card-output/{batch_id}"
        source_hash = str(task.get("source_sha256") or hashlib.sha256(source_body).hexdigest())
        actual_hash = hashlib.sha256(source_body).hexdigest()
        if source_hash != actual_hash:
            raise BatchWriteError("resolved source SHA-256 does not match fetched object")
        source_manifest = build_source_manifest(
            task=task,
            batch_id=batch_id,
            source_hash=source_hash,
            size_bytes=len(source_body),
            contract=contract,
        )
        await self._put_json(f"{prefix}/_batch/source-manifest.json", source_manifest)
        await self._put_json(
            f"{prefix}/_batch/contract-manifest.json",
            {
                "version": contract.version,
                "manifestSha256": contract.manifest_hash,
            },
        )
        card_records: list[dict[str, Any]] = []
        for draft in drafts:
            key = f"{prefix}/cards/{draft.card_type}/{draft.card_id}.md"
            await self._put_verified(key, draft.markdown.encode("utf-8"), "text/markdown")
            card_records.append(
                {
                    "id": draft.card_id,
                    "type": draft.card_type,
                    "s3Key": key,
                    "checksum": hashlib.sha256(draft.markdown.encode("utf-8")).hexdigest(),
                    "sourceLocations": list(draft.source_locations),
                    "confidence": draft.confidence,
                }
            )
        output = {
            "schemaVersion": "2.0",
            "batch": {
                "batchId": batch_id,
                "sourceRoot": source_manifest["source"]["uri"],
                "outputRoot": prefix,
                "cardsRoot": f"{prefix}/cards",
                "reportsRoot": f"{prefix}/reports",
                "createdAt": datetime.now(UTC).isoformat(),
                "contract": source_manifest["contract"],
            },
            "sources": [source_manifest["source"]],
            "cards": card_records,
            "unresolved": (report or {}).get("unresolved", []),
            "conflicts": (report or {}).get("conflicts", []),
            "ontologyProposals": (report or {}).get("ontologyProposals", []),
            "validation": (report or {}).get("validation", {"valid": True}),
        }
        report_key = f"{prefix}/reports/extraction-output.json"
        await self._put_json(report_key, output)
        completion = {
            "batchId": batch_id,
            "tenantId": tenant_id,
            "manifestSha256": hashlib.sha256(
                json.dumps(output, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest(),
            "cardCount": len(card_records),
            "reportKey": report_key,
            "completedAt": datetime.now(UTC).isoformat(),
        }
        completion_key = f"{prefix}/_batch/completion-manifest.json"
        await self._put_json(completion_key, completion)
        logger.info(
            "knowledge_s3_batch_completed",
            extra={
                "event": "knowledge.s3.batch.completed",
                "tenant_id": tenant_id,
                "batch_id": batch_id,
                "card_count": len(card_records),
            },
        )
        return {
            "batch_id": batch_id,
            "prefix": prefix,
            "completion_manifest_key": completion_key,
            "cards": card_records,
            "source_hash": source_hash,
        }

    async def _put_json(self, key: str, payload: dict[str, Any]) -> None:
        await self._put_verified(
            key,
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
            "application/json",
        )

    async def _put_verified(self, key: str, body: bytes, content_type: str) -> None:
        target = ProviderTarget(bucket=self._bucket, key=key)
        await self._storage.put(target, body, content_type)
        if await self._storage.head(target) is None:
            raise BatchWriteError(f"S3 object could not be verified: {key}")
