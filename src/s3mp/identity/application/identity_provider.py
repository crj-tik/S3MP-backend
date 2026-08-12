"""Production identity context provider: resolve sessions and API keys to PrincipalContext."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext
from s3mp.identity.domain.entities import Membership, Session


class SessionStore(Protocol):
    async def find_session(self, token_digest: bytes) -> dict[str, Any] | None: ...


class MembershipStore(Protocol):
    async def get_membership(self, tenant_id: UUID, membership_id: UUID) -> dict[str, Any] | None: ...


class PrincipalStore(Protocol):
    async def get_principal(self, tenant_id: UUID, principal_id: UUID) -> dict[str, Any] | None: ...


@dataclass
class IdentityContextProvider:
    """Resolve credentials to PrincipalContext from database-backed stores."""

    session_store: SessionStore
    membership_store: MembershipStore
    principal_store: PrincipalStore

    async def resolve_session(self, token_digest: bytes) -> PrincipalContext:
        """Resolve a session token digest to a verified PrincipalContext.

        Fails with 401 if the session is expired, revoked, or the principal
        is disabled/suspended.
        """
        session = await self.session_store.find_session(token_digest)
        if session is None:
            raise ApiError("authentication_required", "Session not found", status_code=401)

        now = datetime.now(UTC)
        if session.get("revoked_at") is not None:
            raise ApiError("authentication_required", "Session has been revoked", status_code=401)
        expires = session.get("expires_at")
        if isinstance(expires, datetime) and expires <= now:
            raise ApiError("authentication_required", "Session has expired", status_code=401)

        tid = session["tenant_id"]
        mid = session["membership_id"]
        pid = session["principal_id"]

        membership = await self.membership_store.get_membership(tid, mid)
        if membership is None or membership.get("status") != "active":
            raise ApiError("authentication_required", "Membership is not active", status_code=401)
        if membership.get("expires_at") is not None:
            m_expires = membership["expires_at"]
            if isinstance(m_expires, datetime) and m_expires <= now:
                raise ApiError("authentication_required", "Membership has expired", status_code=401)

        principal = await self.principal_store.get_principal(tid, pid)
        if principal is None or not principal.get("enabled", False):
            raise ApiError("authentication_required", "Principal is not active", status_code=401)

        auth_version = max(
            session.get("authorization_version", 1),
            membership.get("authorization_version", 1),
        )

        return PrincipalContext(
            tenant_id=tid,
            principal_id=pid,
            membership_id=mid,
            authorization_version=auth_version,
        )

    async def resolve_api_key(self, tenant_id: UUID, application_id: UUID) -> PrincipalContext:
        """Resolve an API Key to a PrincipalContext for the application principal.

        API Key contexts have the application principal as both principal and
        membership, with subject_kind='application'.
        """
        principal = await self.principal_store.get_principal(tenant_id, application_id)
        if principal is None or not principal.get("enabled", False):
            raise ApiError("authentication_required", "Application principal is not active", status_code=401)

        return PrincipalContext(
            tenant_id=tenant_id,
            principal_id=application_id,
            membership_id=application_id,
            authorization_version=1,
        )