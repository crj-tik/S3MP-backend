"""Bounded-interval support-access expiry worker."""

import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.common.logging import bind_log_context, configure_logging, log_event, reset_log_context
from s3mp.platform.infrastructure.repository import SqlAlchemyPlatformStore

logger = logging.getLogger(__name__)


async def expire_once(
    store: SqlAlchemyPlatformStore,
    *,
    now: datetime | None = None,
    request_ids: Sequence[UUID] | None = None,
) -> int:
    """Execute one idempotent expiry pass; exposed for integration tests."""
    return await store.expire_support_access(now=now or datetime.now(UTC), request_ids=request_ids)


async def run_once() -> int:
    """Initialize the configured store and execute one expiry pass for health checks."""
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("database configuration is required")
    engine = create_engine(database_url)
    operation_token = bind_log_context(
        operation_id=f"support-access-expiry-{datetime.now(UTC).timestamp():.6f}"
    )
    store = SqlAlchemyPlatformStore(create_session_factory(engine))
    try:
        expired = await expire_once(store)
        log_event(
            logger,
            logging.INFO,
            "support_access_expiry.completed",
            layer="worker",
            count=expired,
            outcome="succeeded",
        )
        return expired
    finally:
        reset_log_context(operation_token)
        await engine.dispose()


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.log_slow_operation_ms)
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("database configuration is required")
    interval = max(1, int(os.getenv("S3MP_SUPPORT_EXPIRY_INTERVAL_SECONDS", "60")))
    engine = create_engine(database_url)
    store = SqlAlchemyPlatformStore(create_session_factory(engine))
    try:
        while True:
            operation_token = bind_log_context(
                operation_id=f"support-access-expiry-{datetime.now(UTC).timestamp():.6f}"
            )
            try:
                expired = await expire_once(store)
                log_event(
                    logger,
                    logging.INFO,
                    "support_access_expiry.completed",
                    layer="worker",
                    count=expired,
                    outcome="succeeded",
                )
            except Exception:
                logger.exception(
                    "support_access_expiry_failed",
                    extra={
                        "event": "support_access_expiry.failed",
                        "layer": "worker",
                        "outcome": "failed",
                    },
                )
            finally:
                reset_log_context(operation_token)
            await asyncio.sleep(interval)
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.log_slow_operation_ms)
    if sys.argv[1:] == ["--once"]:
        asyncio.run(run_once())
        return
    asyncio.run(run())


if __name__ == "__main__":
    main()
