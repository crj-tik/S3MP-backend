"""Expire approved support access; invoke periodically from the deployment scheduler."""

import asyncio
from datetime import UTC, datetime

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.platform.infrastructure.repository import SqlAlchemyPlatformStore


async def expire() -> int:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise SystemExit("database configuration is required")
    engine = create_engine(database_url)
    try:
        store = SqlAlchemyPlatformStore(create_session_factory(engine))
        return await store.expire_support_access(now=datetime.now(UTC))
    finally:
        await engine.dispose()


def main() -> None:
    expired = asyncio.run(expire())
    print(f"Expired {expired} support access requests.")


if __name__ == "__main__":
    main()
