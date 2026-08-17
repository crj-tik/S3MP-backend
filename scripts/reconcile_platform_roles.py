"""Apply additive built-in platform-role permissions to an existing database."""

import asyncio

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.platform.application.baseline import reconcile_platform_roles


async def reconcile() -> set[str]:
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise SystemExit("database configuration is required")
    engine = create_engine(database_url)
    try:
        async with create_session_factory(engine).begin() as session:
            return await reconcile_platform_roles(session)
    finally:
        await engine.dispose()


def main() -> None:
    changed = asyncio.run(reconcile())
    print(f"Reconciled built-in platform roles: {', '.join(sorted(changed)) or 'none'}")


if __name__ == "__main__":
    main()
