"""Run durable file-operation and reconciliation work outside the API process."""

import argparse
import asyncio
import logging
import os
from uuid import uuid4

from redis.asyncio import Redis

from s3mp.applications.infrastructure.repositories import SqlAlchemyApplicationStore
from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.common.logging import bind_log_context, configure_logging, log_event, reset_log_context
from s3mp.common.redis import create_redis
from s3mp.files.application.file_service import FileApplicationService
from s3mp.files.application.operation_worker import FileOperationWorker
from s3mp.files.infrastructure.authorization_repository import SqlAlchemyFileAuthorizationStore
from s3mp.files.infrastructure.ingestion_repository import SqlAlchemyIngestionStore
from s3mp.files.infrastructure.repositories import SqlAlchemyFileStore
from s3mp.files.infrastructure.work_signal import RedisWorkSignal
from s3mp.identity.infrastructure.identity_repository import SqlAlchemyIdentityAdminStore
from s3mp.storage.infrastructure.minio import MinioObjectStorageAdapter
from s3mp.storage.infrastructure.repositories import SqlAlchemyStorageStore

logger = logging.getLogger(__name__)


async def run_once(limit: int, *, redis: Redis | None = None) -> dict[str, int | bool]:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url or not settings.s3_endpoint:
        raise RuntimeError("worker requires database and object-storage configuration")
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
        worker = FileOperationWorker(
            file_store,
            storage_store,
            authorization_store,
            identity_store,
            object_storage,
            application_store,
        )
        completed = await worker.run_once(os.getenv("S3MP_WORKER_ID", str(uuid4())), limit)
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
            processed_operations=len(completed),
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
            count=len(completed),
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
    if args.once:
        asyncio.run(run_once(args.limit))
        return

    async def loop() -> None:
        redis_url = settings.secret_value("redis_url")
        redis = create_redis(redis_url) if redis_url else None
        signal = RedisWorkSignal(redis) if redis is not None else None
        try:
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
                if signal is None or not await signal.wait(args.poll_seconds):
                    # Redis failure is degraded latency only; polling PostgreSQL
                    # on every loop guarantees durable work is still consumed.
                    await asyncio.sleep(0)
        finally:
            if redis is not None:
                await redis.aclose()

    asyncio.run(loop())


if __name__ == "__main__":
    main()
