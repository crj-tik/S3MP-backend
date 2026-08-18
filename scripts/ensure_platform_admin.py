"""Non-interactive, development-only platform administrator bootstrap."""

import asyncio
import os
from typing import cast

from s3mp.common.config import get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.identity.application.security import PasswordHasher
from s3mp.platform.application.baseline import reconcile_platform_roles
from s3mp.platform.infrastructure.repository import SqlAlchemyPlatformStore


async def ensure() -> None:
    if os.environ.get("S3MP_BOOTSTRAP_ADMIN_ENABLED", "false").lower() != "true":
        return
    if os.environ.get("S3MP_ENVIRONMENT", "development").lower() == "production":
        raise RuntimeError("startup platform admin bootstrap is disabled in production")
    settings = get_settings()
    required = {
        "email": os.environ.get("S3MP_BOOTSTRAP_ADMIN_EMAIL"),
        "employee_number": os.environ.get("S3MP_BOOTSTRAP_ADMIN_EMPLOYEE_NUMBER"),
        "display_name": os.environ.get("S3MP_BOOTSTRAP_ADMIN_DISPLAY_NAME"),
        "password": os.environ.get("S3MP_BOOTSTRAP_ADMIN_PASSWORD"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"missing startup bootstrap configuration: {', '.join(missing)}")
    assert all(isinstance(value, str) for value in required.values())
    email = cast(str, required["email"])
    employee_number = cast(str, required["employee_number"])
    display_name = cast(str, required["display_name"])
    password = cast(str, required["password"])
    database_url = settings.secret_value("database_url")
    if not database_url:
        raise RuntimeError("database configuration is required for startup bootstrap")
    engine = create_engine(database_url)
    try:
        sessions = create_session_factory(engine)
        async with sessions.begin() as session:
            await reconcile_platform_roles(session)
        store = SqlAlchemyPlatformStore(sessions)
        user_id = await store.ensure_platform_admin(
            email=email,
            employee_number=employee_number,
            display_name=display_name,
            password_hash=PasswordHasher().hash(password),
        )
        print(f"platform admin bootstrap checked: {user_id}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(ensure())
