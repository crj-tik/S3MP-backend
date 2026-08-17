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
    store = SqlAlchemyPlatformStore(create_session_factory(engine))
    try:
        expired = await expire_once(store)
        logger.info("support_access_expiry_completed", extra={"expired": expired})
        return expired
    finally:
        await engine.dispose()


async def run() -> None:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("database configuration is required")
    interval = max(1, int(os.getenv("S3MP_SUPPORT_EXPIRY_INTERVAL_SECONDS", "60")))
    engine = create_engine(database_url)
    store = SqlAlchemyPlatformStore(create_session_factory(engine))
    try:
        while True:
            try:
                expired = await expire_once(store)
                logger.info("support_access_expiry_completed", extra={"expired": expired})
            except Exception:
                logger.exception("support_access_expiry_failed")
            await asyncio.sleep(interval)
    finally:
        await engine.dispose()


def main() -> None:
    if sys.argv[1:] == ["--once"]:
        asyncio.run(run_once())
        return
    asyncio.run(run())


if __name__ == "__main__":
    main()
