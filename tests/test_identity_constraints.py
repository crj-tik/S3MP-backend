"""Identity FK constraint and enum checks against real postgresql.

Migrated from aiosqlite to real postgresql (async). Tables already exist.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from _infrastructure import real_engine
from s3mp.identity.domain.context import PrincipalContext

INSERT_USER = text(
    "INSERT INTO user_account(id,email,normalized_email,display_name,status) "
    "VALUES (:id,:e,:e,'U','active')"
)
INSERT_PRINCIPAL = text(
    "INSERT INTO principal(id,tenant_id,type,display_name) VALUES (:id,:t,:type,'U')"
)
INSERT_MEMBERSHIP = text(
    "INSERT INTO membership(id,tenant_id,user_id,principal_id,status) "
    "VALUES (:id,:t,:u,:p,'active')"
)
INSERT_HISTORY = text(
    "INSERT INTO membership_status_history"
    "(id,tenant_id,membership_id,to_status,reason,changed_by_principal_id) "
    "VALUES (:id,:t,:m,'active','x',:p)"
)
INSERT_SESSION = text(
    "INSERT INTO auth_session"
    "(id,tenant_id,membership_id,principal_id,token_digest,csrf_digest,"
    "authorization_version,expires_at) VALUES (:id,:t,:m,:p,:d,:c,1,:x)"
)


async def _insert_identity(
    conn: AsyncConnection, tenant_id: UUID, suffix: str, *, create_tenant: bool = True
) -> tuple[UUID, UUID]:
    user_id, principal_id, membership_id = uuid4(), uuid4(), uuid4()
    if create_tenant:
        await conn.execute(
            text("INSERT INTO tenant(id, slug, name) VALUES (:id,:slug,'T')"),
            {"id": str(tenant_id), "slug": suffix},
        )
    await conn.execute(INSERT_USER, {"id": str(user_id), "e": f"{suffix}@test"})
    await conn.execute(
        INSERT_PRINCIPAL, {"id": str(principal_id), "t": str(tenant_id), "type": "user"}
    )
    await conn.execute(
        INSERT_MEMBERSHIP,
        {"id": str(membership_id), "t": str(tenant_id), "u": str(user_id), "p": str(principal_id)},
    )
    return principal_id, membership_id


async def test_history_and_session_reject_cross_tenant_and_mismatch() -> None:
    engine = real_engine()
    async with engine.begin() as conn:
        tenant_a, tenant_b = uuid4(), uuid4()
        _, membership_a = await _insert_identity(conn, tenant_a, str(tenant_a)[:8])
        principal_b, _ = await _insert_identity(conn, tenant_b, str(tenant_b)[:8])
        # PostgreSQL aborts the entire transaction on an IntegrityError, so each
        # expected violation runs inside a savepoint that rolls back independently.
        with pytest.raises(IntegrityError):
            async with conn.begin_nested():
                await conn.execute(
                    INSERT_HISTORY,
                    {"id": str(uuid4()), "t": str(tenant_b), "m": str(membership_a),
                     "p": str(principal_b)},
                )
        with pytest.raises(IntegrityError):
            async with conn.begin_nested():
                await conn.execute(
                    INSERT_SESSION,
                    {
                        "id": str(uuid4()), "t": str(tenant_b), "m": str(membership_a),
                        "p": str(principal_b), "d": b"d", "c": b"c",
                        "x": datetime.now(UTC) + timedelta(hours=1),
                    },
                )
        other_principal, _ = await _insert_identity(
            conn, tenant_a, str(uuid4())[:8], create_tenant=False
        )
        with pytest.raises(IntegrityError):
            async with conn.begin_nested():
                await conn.execute(
                    INSERT_SESSION,
                    {
                        "id": str(uuid4()), "t": str(tenant_a), "m": str(membership_a),
                        "p": str(other_principal), "d": b"d2", "c": b"c2",
                        "x": datetime.now(UTC) + timedelta(hours=1),
                    },
                )
    await engine.dispose()


async def test_database_enum_checks_reject_illegal_values() -> None:
    engine = real_engine()
    async with engine.begin() as conn:
        tenant_id = uuid4()
        await conn.execute(
            text("INSERT INTO tenant(id,slug,name) VALUES (:id,:slug,'T')"),
            {"id": str(tenant_id), "slug": str(tenant_id)[:8]},
        )
        with pytest.raises(IntegrityError):
            await conn.execute(
                INSERT_PRINCIPAL,
                {"id": str(uuid4()), "t": str(tenant_id), "type": "invalid"},
            )
    await engine.dispose()


def test_principal_context_rejects_nil_ids_and_nonpositive_version() -> None:
    valid = uuid4()
    nil = UUID(int=0)
    for values in (
        (nil, valid, valid, 1),
        (valid, nil, valid, 1),
        (valid, valid, nil, 1),
        (valid, valid, valid, 0),
    ):
        with pytest.raises(ValueError):
            PrincipalContext(*values)
