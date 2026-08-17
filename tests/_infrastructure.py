"""Real infrastructure connection constants for integration tests.

Defaults target the docker-deployed services (pg@18110 / redis@18113 / minio@9000)
and may be overridden via ``S3MP_TEST_*`` environment variables. This is a plain
module — NOT a conftest — imported by tests that need real backends, per the
project convention of no shared conftest and locally-scoped fixtures.
"""

from __future__ import annotations

import os
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from s3mp.common.config import Settings
from s3mp.common.database import create_engine, create_session_factory


def _ensure_models_loaded() -> None:
    """Import all ORM model modules so ``Base.metadata`` is complete.

    Stores flush ORM models whose FK constraints reference tables defined in
    other modules (e.g. everything references ``tenant``). Without these
    imports the metadata is incomplete and flush raises
    ``NoReferencedTableError``. Only tests that import this module (real-infra
    tests) trigger this; fake HTTP tests import ``_http`` instead and are
    unaffected.
    """
    import s3mp.applications.infrastructure.models as _apps  # noqa: F401
    import s3mp.audit.infrastructure.models as _audit  # noqa: F401
    import s3mp.authorization.infrastructure.models as _auth  # noqa: F401
    import s3mp.files.infrastructure.models as _files  # noqa: F401
    import s3mp.governance.infrastructure.models as _gov  # noqa: F401
    import s3mp.identity.infrastructure.models as _identity  # noqa: F401
    import s3mp.platform.infrastructure.models as _platform  # noqa: F401
    import s3mp.storage.infrastructure.models as _storage  # noqa: F401
    import s3mp.tenant.infrastructure.models as _tenant  # noqa: F401


_ensure_models_loaded()

# pg: pytest runs on the Windows host, so it must use the published localhost
# port. Dockerized API/worker processes use host.docker.internal instead.
TEST_DATABASE_URL = os.environ.get(
    "S3MP_TEST_DATABASE_URL",
    "postgresql+asyncpg://s3mp_app:bk-s3mp-backend@localhost:18110/s3mp",
)

# redis: dedicated DB 15 to avoid colliding with application data on DB 0.
TEST_REDIS_URL = os.environ.get(
    "S3MP_TEST_REDIS_URL",
    "redis://:Bk-Skill@localhost:18113/15",
)

# minio: local-s3 compose; app credentials, not the MinIO root user.
TEST_S3_ENDPOINT = os.environ.get("S3MP_TEST_S3_ENDPOINT", "http://localhost:9000")
TEST_S3_REGION = os.environ.get("S3MP_TEST_S3_REGION", "us-east-1")
TEST_S3_BUCKET = os.environ.get("S3MP_TEST_S3_BUCKET", "s3mp-dev")
TEST_S3_ACCESS_KEY = os.environ.get("S3MP_TEST_S3_ACCESS_KEY", "s3mp-app")
TEST_S3_SECRET_KEY = os.environ.get("S3MP_TEST_S3_SECRET_KEY", "bk-s3mp-backend")


def real_settings() -> Settings:
    """Return Settings wired to the docker-deployed pg/redis/minio services."""
    return Settings(
        environment="development",
        database_url=SecretStr(TEST_DATABASE_URL),
        redis_url=SecretStr(TEST_REDIS_URL),
        s3_endpoint=TEST_S3_ENDPOINT,
        s3_region=TEST_S3_REGION,
        s3_bucket=TEST_S3_BUCKET,
        s3_access_key=SecretStr(TEST_S3_ACCESS_KEY),
        s3_secret_key=SecretStr(TEST_S3_SECRET_KEY),
        s3_path_style=True,
        readiness_timeout_seconds=30.0,
    )


def real_engine() -> AsyncEngine:
    """Create an async engine bound to the real test database."""
    return create_engine(TEST_DATABASE_URL)


def real_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to ``engine`` (no expire-on-commit)."""
    return create_session_factory(engine)


async def seed_tenant(engine: AsyncEngine, tenant_id: UUID) -> None:
    """Insert a tenant row so FK-dependent seed data can be created."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO tenant(id, slug, name) VALUES (:id, :slug, 'Test')"),
            {"id": str(tenant_id), "slug": f"t-{tenant_id}"},
        )


async def delete_tenant(engine: AsyncEngine, tenant_id: UUID) -> None:
    """Best-effort tenant cleanup.

    Some tables reference tenant with RESTRICT (e.g. audit_event), so deleting
    the tenant row may fail. We swallow the error — tests use unique tenant
    UUIDs so data never conflicts, and the migration test's ``downgrade base``
    periodically resets the entire database.
    """
    from sqlalchemy import text

    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM tenant WHERE id = :id"), {"id": str(tenant_id)})
    except Exception:  # noqa: S110 - best-effort cleanup, FK may block
        pass
