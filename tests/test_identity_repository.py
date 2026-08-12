"""SqlAlchemyIdentityRepository tenant-isolation and session tests against real pg.

Migrated from aiosqlite to real postgresql — tables already exist (migrated).
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from s3mp.common.database import create_engine
from s3mp.identity.domain.context import PrincipalContext
from s3mp.identity.infrastructure.models import (
    MembershipModel,
    MembershipStatus,
    PrincipalModel,
    PrincipalType,
    SessionModel,
    UserModel,
)
from s3mp.identity.infrastructure.repositories import SqlAlchemyIdentityRepository
from s3mp.tenant.infrastructure.models import TenantModel


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    from _infrastructure import TEST_DATABASE_URL

    eng = create_engine(TEST_DATABASE_URL)
    yield eng
    await eng.dispose()


async def seed_identity(
    session: AsyncSession, tenant_id: UUID
) -> tuple[PrincipalContext, UUID]:
    principal_id = uuid4()
    membership_id = uuid4()
    user_id = uuid4()
    session_id = uuid4()
    session.add(TenantModel(id=tenant_id, slug=f"t-{tenant_id}", name="Tenant"))
    session.add(
        UserModel(
            id=user_id,
            email=f"{user_id}@example.test",
            normalized_email=f"{user_id}@example.test",
            display_name="User",
        )
    )
    await session.flush()
    session.add(
        PrincipalModel(
            id=principal_id, tenant_id=tenant_id, type=PrincipalType.USER, display_name="User",
        )
    )
    await session.flush()
    session.add(
        MembershipModel(
            id=membership_id, tenant_id=tenant_id, user_id=user_id,
            principal_id=principal_id, status=MembershipStatus.ACTIVE,
        )
    )
    await session.flush()
    session.add(
        SessionModel(
            id=session_id, tenant_id=tenant_id, membership_id=membership_id,
            principal_id=principal_id, token_digest=uuid4().bytes, csrf_digest=uuid4().bytes,
            authorization_version=1, expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await session.commit()
    return PrincipalContext(tenant_id, principal_id, membership_id, 1), session_id


async def test_repository_treats_cross_tenant_ids_as_not_found(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context_a, session_a = await seed_identity(session, uuid4())
        context_b, _ = await seed_identity(session, uuid4())
        repository = SqlAlchemyIdentityRepository(session)

        assert await repository.get_principal(context_b, context_a.principal_id) is None
        assert await repository.get_membership(context_b, context_a.membership_id) is None
        assert await repository.get_session(context_b, session_a) is None
        assert len(await repository.list_memberships(context_b)) == 1


async def test_composite_foreign_keys_reject_cross_tenant_links(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context_a, _ = await seed_identity(session, uuid4())
        context_b, _ = await seed_identity(session, uuid4())
        foreign_user = UserModel(
            id=uuid4(),
            email=f"{uuid4()}@example.test",
            normalized_email=f"{uuid4()}@example.test",
            display_name="Foreign",
        )
        session.add(foreign_user)
        await session.flush()
        session.add(
            MembershipModel(
                tenant_id=context_b.tenant_id, user_id=foreign_user.id,
                principal_id=context_a.principal_id, status=MembershipStatus.ACTIVE,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_repository_revokes_one_session_and_all_principal_sessions(
    engine: AsyncEngine,
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context, session_id = await seed_identity(session, uuid4())
        repository = SqlAlchemyIdentityRepository(session)

        assert await repository.revoke_session(context, session_id)
        await session.commit()
        revoked = await repository.get_session(context, session_id)
        assert revoked is not None and revoked.revoked_at is not None

        assert (
            await repository.revoke_principal_sessions(context.tenant_id, context.principal_id)
            == 0
        )
