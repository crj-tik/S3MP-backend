"""Alembic migration round-trip tests against real postgresql.

Migrated from aiosqlite to real postgresql. Runs ``upgrade head → downgrade base
→ upgrade head`` on the real ``s3mp`` database (test environment, acceptable to
clear and rebuild). Uses ``asyncio.run()`` for async table inspection since
``command.upgrade`` is sync and uses its own event loop via env.py.
"""

import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from _infrastructure import real_engine

EXPECTED_TABLES = {
    "alembic_version",
    "access_review",
    "api_key",
    "application",
    "application_owner",
    "approval_request",
    "audit_event",
    "auth_session",
    "external_identity",
    "file_ingestion_event",
    "file_ingestion_record",
    "file_object",
    "file_operation",
    "group_member",
    "membership",
    "membership_status_history",
    "multipart_part",
    "multipart_session",
    "permission",
    "principal",
    "quota",
    "quota_reservation",
    "review_item",
    "role",
    "role_binding",
    "role_permission",
    "storage_connection",
    "storage_space",
    "tenant",
    "upload_session",
    "user_account",
    "user_group",
}


def migration_config() -> Config:
    config = Config("alembic.ini")
    # alembic.ini already points to the real pg database; no override needed.
    return config


def _get_tables() -> set[str]:
    async def _run() -> set[str]:
        engine = real_engine()
        try:
            async with engine.connect() as conn:
                tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
            return tables
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _get_version() -> str | None:
    async def _run() -> str | None:
        engine = real_engine()
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            return result.scalar()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_migration_history_has_single_head() -> None:
    from alembic.script import ScriptDirectory

    scripts = ScriptDirectory.from_config(migration_config())
    assert scripts.get_heads() == ["0008_file_ingestion_provenance"]


def test_upgrade_downgrade_upgrade_cycle() -> None:
    config = migration_config()

    command.upgrade(config, "head")
    tables = _get_tables()
    assert tables == EXPECTED_TABLES

    command.downgrade(config, "base")
    tables = _get_tables()
    assert tables == {"alembic_version"}
    assert _get_version() is None

    command.upgrade(config, "head")
    assert _get_version() == "0008_file_ingestion_provenance"
