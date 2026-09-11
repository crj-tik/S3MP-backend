"""Run durable file-operation and reconciliation work outside the API process."""

import argparse
import asyncio
import logging
from uuid import uuid4

from redis.asyncio import Redis

from s3mp.applications.infrastructure.repositories import SqlAlchemyApplicationStore
from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.common.logging import bind_log_context, configure_logging, log_event, reset_log_context
from s3mp.common.rabbitmq import connect_rabbitmq
from s3mp.common.redis import create_redis
from s3mp.files.application.file_service import FileApplicationService
from s3mp.files.application.operation_worker import FileOperationWorker
from s3mp.files.application.rabbitmq_operations import (
    FileOperationOutboxPublisher,
    RabbitMQDeadLetterReceiver,
    RabbitMQFileOperationReceiver,
    run_processing_recovery,
)
from s3mp.files.infrastructure.authorization_repository import SqlAlchemyFileAuthorizationStore
from s3mp.files.infrastructure.ingestion_repository import SqlAlchemyIngestionStore
from s3mp.files.infrastructure.repositories import SqlAlchemyFileStore
from s3mp.identity.infrastructure.identity_repository import SqlAlchemyIdentityAdminStore
from s3mp.storage.infrastructure.minio import MinioObjectStorageAdapter
from s3mp.storage.infrastructure.repositories import SqlAlchemyStorageStore

logger = logging.getLogger(__name__)


async def run_once(limit: int, *, redis: Redis | None = None) -> dict[str, int | bool]:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    rabbitmq_url = settings.secret_value("rabbitmq_url")
    if not database_url or not settings.s3_endpoint or not rabbitmq_url or redis is None:
        raise RuntimeError(
            "worker requires database, Redis, object storage, and RabbitMQ configuration"
        )
    engine = create_engine(database_url)
    operation_token = bind_log_context(operation_id=uuid4().hex)
    try:
        sessions = create_session_factory(engine)
        file_store = SqlAlchemyFileStore(sessions)
        storage_store = SqlAlchemyStorageStore(sessions)
        authorization_store = SqlAlchemyFileAuthorizationStore(sessions)
        identity_store = SqlAlchemyIdentityAdminStore(sessions)
        application_store = SqlAlchemyApplicationStore(sessions)
        object_storage = MinioObjectStorageAdapter(settings)
        connection = await connect_rabbitmq(rabbitmq_url)
        try:
            published = await FileOperationOutboxPublisher(file_store, connection).publish_once(
                limit
            )
            recovered = await run_processing_recovery(
                file_store,
                timeout_seconds=settings.rabbitmq_processing_timeout_seconds,
                max_recoveries=settings.rabbitmq_max_retries,
                limit=limit,
            )
        finally:
            await connection.close()
        ingestion_store = SqlAlchemyIngestionStore(sessions)
        reconciler = FileApplicationService(
            file_store,
            object_storage=object_storage,
            storage_store=storage_store,
            authorization_store=authorization_store,
            ingestion_store=ingestion_store,
            principal_store=identity_store,
            api_key_state_store=application_store,
            reconciliation_max_attempts=settings.worker_max_attempts,
        )
        ingestions = await reconciler.reconcile_pending_ingestions()
        deletions = await reconciler.reconcile_pending_deletions()
        reaped_reservations = await ingestion_store.reap_orphan_reservations(
            limit=settings.worker_batch_size
        )
        purged_files = await file_store.purge_deleted_files(
            settings.worker_retention_days, settings.worker_batch_size
        )
        metrics = await file_store.operation_metrics()
        metrics.update(
            processed_operations=0,
            published_operations=published,
            recovered_operations=recovered,
            reconciled_ingestions=len(ingestions),
            reconciled_deletions=len(deletions),
            reaped_reservations=len(reaped_reservations),
            purged_files=purged_files,
            redis_wakeup_available=redis is not None,
        )
        log_event(
            logger,
            logging.INFO,
            "file.worker.batch.completed",
            layer="worker",
            count=published,
            outcome="succeeded",
        )
        return metrics
    finally:
        reset_log_context(operation_token)
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.log_slow_operation_ms)
    parser.add_argument("--limit", type=int, default=settings.worker_batch_size)
    parser.add_argument("--poll-seconds", type=float, default=settings.worker_poll_seconds)
    args = parser.parse_args()

    async def loop() -> None:
        redis_url = settings.secret_value("redis_url")
        rabbitmq_url = settings.secret_value("rabbitmq_url")
        if not redis_url or not rabbitmq_url:
            raise RuntimeError("worker requires Redis and RabbitMQ configuration")
        redis = create_redis(redis_url)
        connection = await connect_rabbitmq(rabbitmq_url)
        try:
            database_url = settings.secret_value("database_url")
            if not database_url or not settings.s3_endpoint:
                raise RuntimeError("worker requires database and object-storage configuration")
            engine = create_engine(database_url)
            sessions = create_session_factory(engine)
            file_store = SqlAlchemyFileStore(sessions)
            operation_worker = FileOperationWorker(
                file_store,
                SqlAlchemyStorageStore(sessions),
                SqlAlchemyFileAuthorizationStore(sessions),
                SqlAlchemyIdentityAdminStore(sessions),
                MinioObjectStorageAdapter(settings),
                SqlAlchemyApplicationStore(sessions),
            )
            await RabbitMQFileOperationReceiver(
                file_store,
                operation_worker,
                connection,
                redis,
                max_retries=settings.rabbitmq_max_retries,
                prefetch=settings.rabbitmq_prefetch,
            ).consume()
            await RabbitMQDeadLetterReceiver(
                file_store, connection, prefetch=settings.rabbitmq_prefetch
            ).consume()
            if args.once:
                await run_once(args.limit, redis=redis)
                return
            while True:
                try:
                    await run_once(args.limit, redis=redis)
                except Exception:
                    logger.exception(
                        "file_worker_batch_failed",
                        extra={
                            "event": "file.worker.batch.failed",
                            "layer": "worker",
                            "outcome": "failed",
                        },
                    )
                await asyncio.sleep(args.poll_seconds)
        finally:
            await connection.close()
            await redis.aclose()
            if engine is not None:
                await engine.dispose()

    asyncio.run(loop())


if __name__ == "__main__":
    main()
