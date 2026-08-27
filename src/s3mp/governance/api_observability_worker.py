"""Consume asynchronous application API observations into durable projections."""

import argparse
import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from s3mp.common.api_observability import API_USAGE_STREAM
from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.common.logging import bind_log_context, configure_logging, log_event, reset_log_context
from s3mp.common.redis import create_redis
from s3mp.governance.infrastructure.models import (
    ApplicationApiErrorModel,
    ApplicationApiMetricModel,
)

logger = logging.getLogger(__name__)
GROUP = "api-observability"
CONSUMER = os.getenv("S3MP_API_OBSERVABILITY_CONSUMER", "api-observability-1")


def _window(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


async def _consume_one(session_factory: object, fields: dict[str, str]) -> None:
    occurred_at = datetime.fromisoformat(fields["occurred_at"])
    status = int(fields["status_code"])
    values = {
        "tenant_id": UUID(fields["tenant_id"]),
        "application_id": UUID(fields["application_id"]),
        "operation": fields["operation"],
        "window_start": _window(occurred_at),
        "total_count": 1,
        "success_count": int(status < 400),
        "client_error_count": int(400 <= status < 500),
        "server_error_count": int(status >= 500),
    }
    async with session_factory.begin() as session:  # type: ignore[operator]
        stmt = insert(ApplicationApiMetricModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "application_id", "operation", "window_start"],
            set_={
                "total_count": ApplicationApiMetricModel.total_count + 1,
                "success_count": ApplicationApiMetricModel.success_count + values["success_count"],
                "client_error_count": ApplicationApiMetricModel.client_error_count
                + values["client_error_count"],
                "server_error_count": ApplicationApiMetricModel.server_error_count
                + values["server_error_count"],
            },
        )
        await session.execute(stmt)
        if status >= 400:
            session.add(
                ApplicationApiErrorModel(
                    tenant_id=values["tenant_id"],
                    application_id=values["application_id"],
                    operation=fields["operation"],
                    status_code=status,
                    request_id=fields["request_id"],
                    occurred_at=occurred_at,
                )
            )


async def run_once(redis: Redis, session_factory: object, count: int) -> int:
    try:
        await redis.xgroup_create(API_USAGE_STREAM, GROUP, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    rows = await redis.xreadgroup(GROUP, CONSUMER, {API_USAGE_STREAM: ">"}, count=count, block=1000)
    processed = 0
    for _, events in rows:
        for event_id, fields in events:
            await _consume_one(session_factory, fields)
            await redis.xack(API_USAGE_STREAM, GROUP, event_id)
            processed += 1
    return processed


async def log_backlog(redis: Redis) -> None:
    """Emit a safe delivery diagnostic without inspecting request contents."""
    try:
        stream_length = await redis.xlen(API_USAGE_STREAM)
        pending = await redis.xpending(API_USAGE_STREAM, GROUP)
        logger.info(
            "api_observability_backlog",
            extra={"stream_length": stream_length, "pending": pending.get("pending", 0)},
        )
    except Exception:
        logger.exception("api_observability_backlog_check_failed")


async def purge_errors(session_factory: object, retention_days: int = 90) -> int:
    """Remove the minimal troubleshooting references after their retention period."""
    async with session_factory.begin() as session:  # type: ignore[operator]
        result = await session.execute(
            delete(ApplicationApiErrorModel).where(
                ApplicationApiErrorModel.occurred_at
                < datetime.now(UTC) - timedelta(days=retention_days)
            )
        )
        return int(result.rowcount or 0)


async def main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.log_slow_operation_ms)
    database_url, redis_url = (
        settings.secret_value("database_url"),
        settings.secret_value("redis_url"),
    )
    if not database_url or not redis_url:
        raise RuntimeError("api observability worker requires database and redis")
    engine, redis = create_engine(database_url), create_redis(redis_url)
    try:
        sessions = create_session_factory(engine)
        iteration = 0
        while True:
            operation_token = bind_log_context(operation_id="api-observability-batch")
            try:
                processed = await run_once(redis, sessions, settings.worker_batch_size)
                iteration += 1
                if iteration % 60 == 0:
                    removed = await purge_errors(
                        sessions, settings.api_observability_error_retention_days
                    )
                    log_event(
                        logger,
                        logging.INFO,
                        "api_observability.errors_purged",
                        layer="worker",
                        count=removed,
                        outcome="succeeded",
                    )
                    await log_backlog(redis)
                log_event(
                    logger,
                    logging.INFO,
                    "api_observability.batch.completed",
                    layer="worker",
                    count=processed,
                    outcome="succeeded",
                )
                if args.once:
                    return
            except Exception:
                logger.exception(
                    "api_observability_batch_failed",
                    extra={
                        "event": "api_observability.batch.failed",
                        "layer": "worker",
                        "outcome": "failed",
                    },
                )
                if args.once:
                    raise
                await asyncio.sleep(1)
            finally:
                reset_log_context(operation_token)
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main_async())
