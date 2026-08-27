"""Delayed tenant storage-summary refresh worker."""

import asyncio
import logging
import os

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.governance.infrastructure.dashboard_repository import SqlAlchemyDashboardStore

logger = logging.getLogger(__name__)


async def main_async() -> None:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("dashboard scheduler requires database")
    interval = max(60, int(os.getenv("S3MP_DASHBOARD_SUMMARY_INTERVAL_SECONDS", "3600")))
    engine = create_engine(database_url)
    try:
        store = SqlAlchemyDashboardStore(create_session_factory(engine))
        while True:
            try:
                refreshed = await store.refresh_storage_summaries()
                logger.info("dashboard_storage_summary_refreshed", extra={"tenants": refreshed})
            except Exception:
                logger.exception("dashboard_storage_summary_refresh_failed")
            await asyncio.sleep(interval)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main_async())
