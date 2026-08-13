"""Interactively create the first platform administrator without printing a secret."""

import argparse
import asyncio
import getpass

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.identity.application.security import PasswordHasher
from s3mp.platform.application.baseline import seed_platform_roles
from s3mp.platform.infrastructure.repository import SqlAlchemyPlatformStore


async def bootstrap(email: str, display_name: str) -> None:
    password = getpass.getpass("Initial platform administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("password confirmation did not match")
    settings = get_settings()
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise SystemExit("database configuration is required")
    engine = create_engine(database_url)
    try:
        sessions = create_session_factory(engine)
        async with sessions.begin() as session:
            await seed_platform_roles(session)
        store = SqlAlchemyPlatformStore(sessions)
        await store.create_initial_platform_admin(
            email=email,
            display_name=display_name,
            password_hash=PasswordHasher().hash(password),
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap S3MP's first platform administrator")
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    asyncio.run(bootstrap(args.email, args.display_name))
    print("Platform administrator bootstrap completed.")


if __name__ == "__main__":
    main()
