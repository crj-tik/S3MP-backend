"""Delayed tenant storage-summary refresh worker."""

import asyncio
import logging
import os

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.common.logging import bind_log_context, configure_logging, log_event, reset_log_context
from s3mp.governance.infrastructure.dashboard_repository import SqlAlchemyDashboardStore

logger = logging.getLogger(__name__)


async def main_async() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format, settings.log_slow_operation_ms)
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("dashboard scheduler requires database")
    interval = max(60, int(os.getenv("S3MP_DASHBOARD_SUMMARY_INTERVAL_SECONDS", "3600")))
    engine = create_engine(database_url)
    try:
        store = SqlAlchemyDashboardStore(create_session_factory(engine))
        while True:
            operation_token = bind_log_context(operation_id="dashboard-storage-summary")
            try:
                refreshed = await store.refresh_storage_summaries()
                log_event(
                    logger,
                    logging.INFO,
                    "dashboard.storage_summary.completed",
                    layer="worker",
                    count=refreshed,
                    outcome="succeeded",
                )
            except Exception:
                logger.exception(
                    "dashboard_storage_summary_refresh_failed",
                    extra={
                        "event": "dashboard.storage_summary.failed",
                        "layer": "worker",
                        "outcome": "failed",
                    },
                )
            finally:
                reset_log_context(operation_token)
            await asyncio.sleep(interval)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main_async())
