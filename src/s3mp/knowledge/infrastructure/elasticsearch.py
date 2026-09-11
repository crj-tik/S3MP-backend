"""Elasticsearch projection for S3-authoritative knowledge cards."""

from __future__ import annotations

from typing import Any

from elasticsearch import AsyncElasticsearch

from s3mp.knowledge.application.card_contract import ParsedCard, indexed_metadata
from s3mp.knowledge.contracts import KnowledgeContract


def knowledge_index_mapping() -> dict[str, Any]:
    """A lexical-only tenant-filtered mapping; vector fields are intentionally absent."""
    return {
        "dynamic": True,
        "properties": {
            "tenant_id": {"type": "keyword"},
            "card_id": {"type": "keyword"},
            "card_type": {"type": "keyword"},
            "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "body": {"type": "text"},
            "s3_key": {"type": "keyword", "index": False},
            "batch_id": {"type": "keyword"},
            "source_locations": {"type": "object", "enabled": False},
            "metadata": {"type": "object", "dynamic": True},
        },
    }


class KnowledgeSearchIndex:
    def __init__(
        self, client: AsyncElasticsearch, index_name: str, contract: KnowledgeContract
    ) -> None:
        self._client, self._index_name, self._contract = client, index_name, contract

    async def ensure_index(self) -> None:
        if not await self._client.indices.exists(index=self._index_name):
            await self._client.indices.create(
                index=self._index_name, mappings=knowledge_index_mapping()
            )

    async def upsert(
        self,
        *,
        tenant_id: str,
        batch_id: str,
        s3_key: str,
        card: ParsedCard,
    ) -> None:
        frontmatter = card.frontmatter
        document = {
            "tenant_id": tenant_id,
            "batch_id": batch_id,
            "card_id": card.card_id,
            "card_type": card.card_type,
            "title": frontmatter.get("title") or frontmatter.get("name") or card.card_id,
            "body": card.body,
            "s3_key": s3_key,
            "source_locations": frontmatter.get("sourceLocations", []),
            "metadata": indexed_metadata(card, contract=self._contract),
        }
        await self._client.index(
            index=self._index_name,
            id=f"{tenant_id}:{batch_id}:{card.card_id}",
            document=document,
            refresh=False,
        )
