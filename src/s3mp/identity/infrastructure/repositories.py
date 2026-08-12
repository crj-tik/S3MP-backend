"""SQLAlchemy implementation of tenant-safe identity repositories."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from s3mp.identity.application.security import PasswordCredential
from s3mp.identity.domain.context import PrincipalContext
from s3mp.identity.domain.entities import Membership, Principal, Session
from s3mp.identity.infrastructure.models import (
    MembershipModel,
    PrincipalModel,
    SessionModel,
    UserModel,
)


class SqlAlchemyIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_principal(
        self, context: PrincipalContext, principal_id: UUID
    ) -> Principal | None:
        model = await self._session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.tenant_id == context.tenant_id,
                PrincipalModel.id == principal_id,
            )
        )
        return _principal(model) if model is not None else None

    async def get_membership(
        self, context: PrincipalContext, membership_id: UUID
    ) -> Membership | None:
        model = await self._session.scalar(
            select(MembershipModel).where(
                MembershipModel.tenant_id == context.tenant_id,
                MembershipModel.id == membership_id,
            )
        )
        return _membership(model) if model is not None else None

    async def list_memberships(self, context: PrincipalContext) -> Sequence[Membership]:
        models = (
            await self._session.scalars(
                select(MembershipModel)
                .where(MembershipModel.tenant_id == context.tenant_id)
                .order_by(MembershipModel.id)
            )
        ).all()
        return tuple(_membership(model) for model in models)

    async def get_session(self, context: PrincipalContext, session_id: UUID) -> Session | None:
        model = await self._session.scalar(
            select(SessionModel).where(
                SessionModel.tenant_id == context.tenant_id,
                SessionModel.id == session_id,
            )
        )
        return _session(model) if model is not None else None

    async def revoke_session(self, context: PrincipalContext, session_id: UUID) -> bool:
        result = await self._session.execute(
            update(SessionModel)
            .where(
                SessionModel.tenant_id == context.tenant_id,
                SessionModel.id == session_id,
                SessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        return result.rowcount == 1  # type: ignore[no-any-return, attr-defined]

    async def revoke_principal_sessions(self, tenant_id: UUID, principal_id: UUID) -> int:
        result = await self._session.execute(
            update(SessionModel)
            .where(
                SessionModel.tenant_id == tenant_id,
                SessionModel.principal_id == principal_id,
                SessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        return result.rowcount  # type: ignore[no-any-return, attr-defined]

    async def find_by_normalized_email(self, normalized_email: str) -> "PasswordCredential | None":
        model = await self._session.scalar(
            select(UserModel).where(UserModel.normalized_email == normalized_email)
        )
        if model is None:
            return None
        return PasswordCredential(model.id, model.password_hash)


def _principal(model: PrincipalModel) -> Principal:
    return Principal(
        id=model.id,
        tenant_id=model.tenant_id,
        type=model.type.value,
        display_name=model.display_name,
        enabled=model.enabled,
    )


def _membership(model: MembershipModel) -> Membership:
    return Membership(
        id=model.id,
        tenant_id=model.tenant_id,
        user_id=model.user_id,
        principal_id=model.principal_id,
        status=model.status.value,
        authorization_version=model.authorization_version,
        expires_at=model.expires_at,
    )


def _session(model: SessionModel) -> Session:
    return Session(
        id=model.id,
        tenant_id=model.tenant_id,
        membership_id=model.membership_id,
        principal_id=model.principal_id,
        authorization_version=model.authorization_version,
        expires_at=model.expires_at,
        revoked_at=model.revoked_at,
    )
