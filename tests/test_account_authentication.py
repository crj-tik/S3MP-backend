"""Account browser authentication must stay separate from tenant authority."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from s3mp.common.errors import ApiError
from s3mp.identity.application.security import (
    InMemoryLoginRateLimiter,
    LocalPasswordAuthenticator,
    PasswordCredential,
    PasswordHasher,
    SessionTokenService,
)
from s3mp.platform.application.account_authentication import AccountAuthenticationService
from s3mp.platform.domain.context import PlatformContext


class AccountStore:
    def __init__(self) -> None:
        self.user_id = uuid4()
        self.password_hash = PasswordHasher().hash("correct-password")
        self.sessions: list[tuple[UUID, bytes, bytes, datetime]] = []
        self.tenant_sessions: list[UUID] = []

    async def find_by_normalized_email(self, _email: str) -> PasswordCredential:
        return PasswordCredential(self.user_id, self.password_hash)

    async def create_account_session(
        self, user_id: UUID, token_digest: bytes, csrf_digest: bytes, expires_at: datetime
    ) -> UUID:
        session_id = uuid4()
        self.sessions.append((user_id, token_digest, csrf_digest, expires_at))
        return session_id

    async def resolve_account_session(self, _token_digest: bytes) -> PlatformContext | None:
        return None

    async def revoke_account_session(self, _session_id: UUID) -> None:
        return None

    async def account_summary(self, user_id: UUID) -> dict[str, object] | None:
        return {"account": {"id": str(user_id)}, "tenants": []}

    async def create_tenant_session(
        self,
        _user_id: UUID,
        tenant_id: UUID,
        _token_digest: bytes,
        _csrf_digest: bytes,
        _expires_at: datetime,
    ) -> bool:
        allowed = tenant_id.int % 2 == 0
        if allowed:
            self.tenant_sessions.append(tenant_id)
        return allowed


def service(store: AccountStore) -> AccountAuthenticationService:
    tokens = SessionTokenService(b"x" * 32)
    return AccountAuthenticationService(
        store,
        LocalPasswordAuthenticator(store, InMemoryLoginRateLimiter()),
        tokens,
        session_ttl_seconds=900,
    )


@pytest.mark.asyncio
async def test_login_returns_context_but_not_raw_session_token() -> None:
    store = AccountStore()
    result, session_token, csrf_token = await service(store).login(
        "account@example.test", "correct-password", rate_limit_key="test"
    )

    assert result == {"account": {"id": str(store.user_id)}, "tenants": []}
    assert session_token not in str(result)
    assert csrf_token not in str(result)
    assert store.sessions[0][0] == store.user_id
    assert store.sessions[0][3] > datetime.now(UTC) + timedelta(minutes=14)


@pytest.mark.asyncio
async def test_tenant_selection_denial_does_not_return_a_tenant_session() -> None:
    store = AccountStore()
    denied_tenant = UUID(int=1)
    context = PlatformContext(store.user_id, uuid4(), frozenset({"platform.tenants.manage"}))

    with pytest.raises(ApiError) as raised:
        await service(store).select_tenant(context, denied_tenant)

    assert raised.value.code == "tenant_session_denied"
    assert store.tenant_sessions == []
