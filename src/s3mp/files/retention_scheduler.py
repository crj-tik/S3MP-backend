"""Durable soft-delete retention scheduler.

Redis is deliberately only a due-time index. PostgreSQL's retained-file state
and outbox make restart and AOF-loss recovery safe.
"""

import argparse
import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.common.logging import bind_log_context, configure_logging, log_event, reset_log_context
from s3mp.common.redis import create_redis
from s3mp.common.timezone import CHINA_TIMEZONE
from s3mp.files.infrastructure.repositories import SqlAlchemyFileStore
from s3mp.storage.domain.policy import ProviderTarget
from s3mp.storage.infrastructure.minio import MinioObjectStorageAdapter
from s3mp.storage.infrastructure.repositories import SqlAlchemyStorageStore

RETENTION_DUE_KEY = "s3mp:file-retention:due"
logger = logging.getLogger(__name__)


async def _dispatch_outbox(store: SqlAlchemyFileStore, redis: Redis, limit: int) -> int:
    count = 0
    for record in await store.list_retention_outbox(limit):
        try:
            file_id = record["file_id"]
            if record["action"] == "schedule":
                due_at = datetime.fromisoformat(str(record["due_at"]))
                await redis.zadd(RETENTION_DUE_KEY, {file_id: due_at.timestamp()})
            else:
                await redis.zrem(RETENTION_DUE_KEY, file_id)
            await store.acknowledge_retention_outbox(UUID(record["id"]), success=True)
            count += 1
        except (RedisError, ValueError, TypeError):
            await store.acknowledge_retention_outbox(UUID(record["id"]), success=False)
    return count


async def _reconcile_index(store: SqlAlchemyFileStore, redis: Redis, limit: int) -> int:
    """Reinsert missing/stale queue members from the indexed persisted state."""
    count = 0
    for record in await store.retention_reconciliation_candidates(limit):
        scheduled_at = record.get("purge_next_retry_at") or record.get("purge_due_at")
        if scheduled_at is None:
            continue
        try:
            await redis.zadd(
                RETENTION_DUE_KEY,
                {str(record["id"]): datetime.fromisoformat(str(scheduled_at)).timestamp()},
            )
            count += 1
        except RedisError:
            break
    return count


async def _purge_due(
    store: SqlAlchemyFileStore,
    storage_store: SqlAlchemyStorageStore,
    object_storage: MinioObjectStorageAdapter,
    redis: Redis,
    limit: int,
    max_attempts: int,
) -> int:
    now = datetime.now(UTC).timestamp()
    # ZPOPMIN avoids repeatedly looking at a future head and makes one worker
    # claim each member. The DB row lock remains the final race authority.
    rows = await redis.zpopmin(RETENTION_DUE_KEY, count=limit)
    purged = 0
    for raw_file_id, score in rows:
        if float(score) > now:
            await redis.zadd(RETENTION_DUE_KEY, {str(raw_file_id): float(score)})
            break
        try:
            record = await store.claim_retained_file_for_purge(UUID(str(raw_file_id)))
            if record is None:
                continue
            space = await storage_store.get_space(
                UUID(str(record["tenant_id"])), UUID(str(record["storage_space_id"]))
            )
            if space is None:
                raise RuntimeError("retained file storage space is unavailable")
            await object_storage.delete(
                ProviderTarget(bucket=str(space["bucket"]), key=str(record["object_key"]))
            )
            await store.finalize_retained_file_purge(
                UUID(str(record["tenant_id"])), UUID(str(record["id"]))
            )
            purged += 1
        except Exception:
            # The row is still hidden. The indexed reconciliation pass requeues
            # it using its durable retry deadline.
            await store.record_retained_purge_failure(UUID(str(raw_file_id)), max_attempts)
    return purged


async def run_once(limit: int) -> dict[str, int]:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    redis_url = settings.secret_value("redis_url")
    if not database_url or not redis_url or not settings.s3_endpoint:
        raise RuntimeError("retention scheduler requires database, redis, and object storage")
    engine = create_engine(database_url)
    redis = create_redis(redis_url)
    operation_token = bind_log_context(operation_id="file-retention-batch")
    try:
        sessions = create_session_factory(engine)
        store = SqlAlchemyFileStore(sessions)
        storage_store = SqlAlchemyStorageStore(sessions)
        dispatched = await _dispatch_outbox(store, redis, limit)
        reconciled = await _reconcile_index(store, redis, limit)
        purged = await _purge_due(
            store,
            storage_store,
            MinioObjectStorageAdapter(settings),
            redis,
            limit,
            settings.worker_max_attempts,
        )
        metrics = {"dispatched": dispatched, "reconciled": reconciled, "purged": purged}
        log_event(
            logger,
            logging.INFO,
            "file.retention.batch.completed",
            layer="worker",
            count=sum(metrics.values()),
            outcome="succeeded",
        )
        return metrics
    finally:
        reset_log_context(operation_token)
        await redis.aclose()
        await engine.dispose()


def _seconds_until_china_midnight() -> float:
    now = datetime.now(CHINA_TIMEZONE)
    tomorrow = (now + timedelta(days=1)).date()
    midnight = datetime.combine(tomorrow, datetime.min.time(), tzinfo=CHINA_TIMEZONE)
    return max(1.0, (midnight - now).total_seconds())


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.log_slow_operation_ms)
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=settings.worker_batch_size)
    args = parser.parse_args()
    if args.once:
        asyncio.run(run_once(args.limit))
        return

    async def loop() -> None:
        # Reconciliation/outbox dispatch runs at process start; physical due
        # purge is scheduled for each Asia/Shanghai midnight thereafter.
        try:
            await run_once(args.limit)
        except Exception:
            logger.exception(
                "file_retention_initial_batch_failed",
                extra={
                    "event": "file.retention.batch.failed",
                    "layer": "worker",
                    "outcome": "failed",
                },
            )
        while True:
            await asyncio.sleep(_seconds_until_china_midnight())
            while True:
                try:
                    metrics = await run_once(args.limit)
                except Exception:
                    logger.exception(
                        "file_retention_batch_failed",
                        extra={
                            "event": "file.retention.batch.failed",
                            "layer": "worker",
                            "outcome": "failed",
                        },
                    )
                    break
                if metrics["purged"] < args.limit:
                    break

    asyncio.run(loop())


if __name__ == "__main__":
    main()
