"""Dedicated knowledge analysis and Elasticsearch projection workers."""

from __future__ import annotations

import argparse
import asyncio
import logging

from elasticsearch import AsyncElasticsearch

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.common.logging import configure_logging
from s3mp.common.rabbitmq import connect_rabbitmq
from s3mp.common.redis import create_redis
from s3mp.knowledge.application.analysis_executor import KnowledgeAnalysisExecutor
from s3mp.knowledge.application.batch_writer import S3KnowledgeBatchWriter
from s3mp.knowledge.application.index_executor import KnowledgeIndexExecutor
from s3mp.knowledge.application.llm_client import OpenAICompatibleKnowledgeClient
from s3mp.knowledge.application.rabbitmq import (
    KnowledgeAnalysisReceiver,
    KnowledgeIndexReceiver,
    KnowledgeOutboxPublisher,
)
from s3mp.knowledge.contracts import load_contract
from s3mp.knowledge.infrastructure.elasticsearch import KnowledgeSearchIndex
from s3mp.knowledge.infrastructure.repositories import SqlAlchemyKnowledgeStore
from s3mp.storage.infrastructure.minio import MinioObjectStorageAdapter

logger = logging.getLogger(__name__)


async def run(mode: str) -> None:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    rabbitmq_url = settings.secret_value("rabbitmq_url")
    redis_url = settings.secret_value("redis_url")
    if (
        not database_url
        or not rabbitmq_url
        or not redis_url
        or not settings.s3_endpoint
        or not settings.s3_bucket
    ):
        raise RuntimeError("knowledge worker requires database, RabbitMQ and S3 configuration")
    engine = create_engine(database_url)
    sessions = create_session_factory(engine)
    contract = load_contract()
    storage = MinioObjectStorageAdapter(settings)
    connection = await connect_rabbitmq(rabbitmq_url)
    redis = create_redis(redis_url)
    try:
        store = SqlAlchemyKnowledgeStore(sessions, redis)
        if mode == "analysis":
            provider, model, base_url = (
                settings.knowledge_llm_provider,
                settings.knowledge_llm_model,
                settings.knowledge_llm_base_url,
            )
            api_key = settings.secret_value("knowledge_llm_api_key")
            if not provider or not model or not base_url or not api_key:
                raise RuntimeError("analysis worker requires knowledge LLM configuration")
            executor = KnowledgeAnalysisExecutor(
                store=store,
                object_storage=storage,
                llm=OpenAICompatibleKnowledgeClient(
                    provider, base_url, api_key, model, settings.knowledge_llm_timeout_seconds
                ),
                writer=S3KnowledgeBatchWriter(storage, bucket=settings.s3_bucket),
                contract=contract,
                bucket=settings.s3_bucket,
                max_source_bytes=settings.knowledge_max_source_bytes,
                max_extracted_characters=settings.knowledge_max_extracted_characters,
                chunk_characters=settings.knowledge_chunk_characters,
            )
            receiver = KnowledgeAnalysisReceiver(
                store,
                connection,
                executor,
                max_retries=settings.knowledge_max_retries,
                prefetch=settings.knowledge_worker_prefetch,
            )
            await receiver.consume()
            while True:
                await store.recover_stale_processing(
                    settings.knowledge_processing_timeout_seconds,
                    settings.knowledge_max_retries,
                )
                await KnowledgeOutboxPublisher(store, connection).publish_once()
                await asyncio.sleep(settings.worker_poll_seconds)
        else:
            endpoint = settings.elasticsearch_url
            if not endpoint:
                raise RuntimeError("index worker requires elasticsearch_url")
            api_key = settings.secret_value("elasticsearch_api_key")
            client = (
                AsyncElasticsearch(endpoint, api_key=api_key)
                if api_key
                else AsyncElasticsearch(endpoint)
            )
            try:
                index = KnowledgeSearchIndex(
                    client, settings.knowledge_elasticsearch_index, contract
                )
                await index.ensure_index()
                await KnowledgeIndexReceiver(
                    connection,
                    KnowledgeIndexExecutor(
                        storage=storage,
                        search_index=index,
                        contract=contract,
                        bucket=settings.s3_bucket,
                    ),
                    store,
                    prefetch=settings.knowledge_worker_prefetch,
                ).consume()
                # Index events are emitted by the transactional outbox after S3
                # completion.  Keep publishing here as well as in the analysis
                # worker: otherwise cards already written to S3 could remain in
                # PostgreSQL's outbox forever when no analysis worker is running.
                publisher = KnowledgeOutboxPublisher(store, connection)
                while True:
                    await publisher.publish_once()
                    await asyncio.sleep(settings.worker_poll_seconds)
            finally:
                await client.close()
    finally:
        await redis.aclose()
        await connection.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("analysis", "index"))
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.log_slow_operation_ms)
    asyncio.run(run(args.mode))


if __name__ == "__main__":
    main()
