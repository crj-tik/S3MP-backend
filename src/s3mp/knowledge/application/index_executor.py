"""Independent S3-card to Elasticsearch projection executor."""

from __future__ import annotations

import json
from typing import Any, Protocol

from s3mp.knowledge.application.card_contract import parse_card
from s3mp.knowledge.contracts import KnowledgeContract
from s3mp.knowledge.infrastructure.elasticsearch import KnowledgeSearchIndex
from s3mp.storage.domain.policy import ProviderTarget


class IndexObjectStorage(Protocol):
    async def get(self, target: ProviderTarget, *, max_bytes: int) -> bytes | None: ...


class KnowledgeIndexExecutor:
    """Reads only completed card objects; it never touches source files or LLMs."""

    def __init__(
        self,
        *,
        storage: IndexObjectStorage,
        search_index: KnowledgeSearchIndex,
        contract: KnowledgeContract,
        bucket: str,
        max_card_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self._storage, self._index = storage, search_index
        self._contract, self._bucket, self._max_card_bytes = contract, bucket, max_card_bytes

    async def execute(self, event: dict[str, Any]) -> tuple[str, str | None]:
        key = event.get("s3_key")
        if not isinstance(key, str) or not key:
            return "failed", "missing_card_s3_key"
        completion_key = event.get("completion_manifest_key")
        if isinstance(completion_key, str) and completion_key:
            completion = await self._storage.get(
                ProviderTarget(bucket=self._bucket, key=completion_key),
                max_bytes=256 * 1024,
            )
            if completion is None:
                return "retry", "completion_manifest_not_found"
            try:
                manifest = json.loads(completion)
            except (TypeError, ValueError, UnicodeDecodeError):
                return "retry", "completion_manifest_invalid"
            if not isinstance(manifest, dict) or str(manifest.get("batchId")) != str(
                event.get("batch_id")
            ):
                return "retry", "completion_manifest_mismatch"
        body = await self._storage.get(
            ProviderTarget(bucket=self._bucket, key=key), max_bytes=self._max_card_bytes
        )
        if body is None:
            return "retry", "card_object_not_found"
        card = parse_card(body.decode("utf-8"), contract=self._contract)
        await self._index.upsert(
            tenant_id=str(event["tenant_id"]),
            batch_id=str(event["batch_id"]),
            s3_key=key,
            card=card,
        )
        return "completed", None
