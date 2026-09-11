"""Controlled rebuild of Elasticsearch from completed S3 card objects."""

from __future__ import annotations

import argparse
import asyncio

from elasticsearch import AsyncElasticsearch

from s3mp.common.config import get_settings
from s3mp.knowledge.application.card_contract import parse_card
from s3mp.knowledge.contracts import load_contract
from s3mp.knowledge.infrastructure.elasticsearch import KnowledgeSearchIndex
from s3mp.storage.domain.policy import ProviderTarget
from s3mp.storage.infrastructure.minio import MinioObjectStorageAdapter


async def rebuild(tenant_id: str) -> int:
    settings = get_settings()
    if not settings.s3_bucket or not settings.elasticsearch_url:
        raise RuntimeError("S3 bucket and Elasticsearch URL are required")
    storage = MinioObjectStorageAdapter(settings)
    client = (
        AsyncElasticsearch(
            settings.elasticsearch_url,
            api_key=settings.secret_value("elasticsearch_api_key"),
        )
        if settings.secret_value("elasticsearch_api_key")
        else AsyncElasticsearch(settings.elasticsearch_url)
    )
    try:
        contract = load_contract()
        index = KnowledgeSearchIndex(client, settings.knowledge_elasticsearch_index, contract)
        await index.ensure_index()
        count, token = 0, None
        prefix = f"tenants/{tenant_id}/knowledge-card-output/"
        while True:
            objects, token = await storage.list_objects(prefix, continuation_token=token)
            for obj in objects:
                if not obj.key.endswith(".md") or "/cards/" not in obj.key:
                    continue
                body = await storage.get(
                    ProviderTarget(bucket=settings.s3_bucket, key=obj.key),
                    max_bytes=settings.knowledge_max_source_bytes,
                )
                if body is None:
                    continue
                card = parse_card(body.decode("utf-8"), contract=contract)
                parts = obj.key.split("/")
                batch_id = parts[3] if len(parts) > 3 else "rebuild"
                await index.upsert(
                    tenant_id=tenant_id, batch_id=batch_id, s3_key=obj.key, card=card
                )
                count += 1
            if not token:
                break
        return count
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id")
    args = parser.parse_args()
    print(asyncio.run(rebuild(args.tenant_id)))


if __name__ == "__main__":
    main()
