"""Alembic migration environment."""

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from s3mp.applications.infrastructure import models as application_models  # noqa: F401
from s3mp.audit.infrastructure import models as audit_models  # noqa: F401
from s3mp.authorization.infrastructure import models as authorization_models  # noqa: F401
from s3mp.common.database import Base
from s3mp.files.infrastructure import models as file_models  # noqa: F401
from s3mp.governance.infrastructure import access_review_models  # noqa: F401
from s3mp.governance.infrastructure import models as governance_models  # noqa: F401
from s3mp.identity.infrastructure import models as identity_models  # noqa: F401
from s3mp.platform.infrastructure import models as platform_models  # noqa: F401
from s3mp.storage.infrastructure import models as storage_models  # noqa: F401
from s3mp.tenant.infrastructure import models as tenant_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
# The Compose/runtime environment is authoritative.  Keeping a local URL in
# alembic.ini is useful for host development, but must not override the URL
# injected into an API/worker container.
database_url = os.getenv("S3MP_DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(
            lambda sync_connection: context.configure(
                connection=sync_connection, target_metadata=target_metadata
            )
        )
        async with connection.begin():
            await connection.run_sync(lambda _: context.run_migrations())
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
