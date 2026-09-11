"""One-time RabbitMQ cutover for legacy file-operation rows.

Run only after stopping deployments that use the PostgreSQL polling worker and
before starting the RabbitMQ worker.  It is intentionally separate from the
Alembic schema migration so a rollback never silently changes live work.
"""

import asyncio

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.files.infrastructure.repositories import SqlAlchemyFileStore


async def main() -> None:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("database configuration is required")
    engine = create_engine(database_url)
    try:
        store = SqlAlchemyFileStore(create_session_factory(engine))
        while await store.enqueue_legacy_operations():
            pass
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
