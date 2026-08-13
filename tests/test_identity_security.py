from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from s3mp.common.auth_middleware import _resolve_api_key
from s3mp.common.config import Settings
from s3mp.identity.application.security import (
    AuthenticationFailed,
    InMemoryLoginRateLimiter,
    LocalPasswordAuthenticator,
    LoginRateLimited,
    PasswordCredential,
    PasswordHasher,
    SessionCookiePolicy,
    SessionTokenService,
)
from s3mp.identity.domain.context import PrincipalContext, is_session_usable, select_membership
from s3mp.identity.domain.entities import Membership, Session
from s3mp.main import create_app


def test_password_hash_is_salted_and_verifies() -> None:
    hasher = PasswordHasher(n=2**10)
    first = hasher.hash("correct horse battery staple")
    second = hasher.hash("correct horse battery staple")

    assert first != second
    assert hasher.verify("correct horse battery staple", first)
    assert not hasher.verify("wrong", first)
    assert not hasher.verify("correct horse battery staple", "not-a-hash")


def test_session_tokens_are_opaque_and_only_digests_are_persisted() -> None:
    service = SessionTokenService(b"p" * 32)
    tokens = service.issue()

    assert tokens.session_token != tokens.csrf_token
    digest = service.digest(tokens.session_token)
    assert service.verify(tokens.session_token, digest)
    assert not service.verify("wrong", digest)
    assert service.verify_csrf(tokens.csrf_token, tokens.csrf_token)
    assert not service.verify_csrf(tokens.csrf_token, "wrong")


def test_session_service_requires_a_strong_pepper() -> None:
    with pytest.raises(ValueError):
        SessionTokenService(b"short")


@pytest.mark.asyncio
async def test_login_rate_limiter_allows_limit_then_blocks_until_window_expires() -> None:
    limiter = InMemoryLoginRateLimiter(limit=2, window_seconds=60)

    assert await limiter.allow("user@example.test", now=100)
    assert await limiter.allow("user@example.test", now=101)
    assert not await limiter.allow("user@example.test", now=102)
    assert await limiter.allow("user@example.test", now=161)
    assert await limiter.allow("other@example.test", now=102)


def test_browser_session_cookie_defaults_are_safe() -> None:
    policy = SessionCookiePolicy()

    assert policy.httponly
    assert policy.secure
    assert policy.samesite == "lax"


class CredentialStore:
    def __init__(self, credential: PasswordCredential | None) -> None:
        self.credential = credential

    async def find_by_normalized_email(self, normalized_email: str) -> PasswordCredential | None:
        assert normalized_email == "user@example.test"
        return self.credential


@pytest.mark.asyncio
async def test_local_password_auth_normalizes_email_and_hides_missing_users() -> None:
    user_id = uuid4()
    hasher = PasswordHasher()
    service = LocalPasswordAuthenticator(
        CredentialStore(PasswordCredential(user_id, hasher.hash("password"))),
        InMemoryLoginRateLimiter(),
    )

    assert (
        await service.authenticate(" User@Example.Test ", "password", rate_limit_key="ip")
        == user_id
    )
    with pytest.raises(AuthenticationFailed):
        await service.authenticate("user@example.test", "wrong", rate_limit_key="ip-2")


@pytest.mark.asyncio
async def test_local_password_auth_enforces_rate_limit_before_lookup() -> None:
    service = LocalPasswordAuthenticator(CredentialStore(None), InMemoryLoginRateLimiter(limit=1))

    with pytest.raises(AuthenticationFailed):
        await service.authenticate("user@example.test", "wrong", rate_limit_key="ip")
    with pytest.raises(LoginRateLimited):
        await service.authenticate("user@example.test", "wrong", rate_limit_key="ip")


def test_tenant_selection_uses_only_active_nonexpired_membership() -> None:
    membership = Membership(uuid4(), uuid4(), uuid4(), uuid4(), "active", 3, None)

    context = select_membership([membership], membership.tenant_id)

    assert context.tenant_id == membership.tenant_id
    assert context.authorization_version == 3


def test_tenant_selection_skips_suspended_to_reach_active_membership() -> None:
    # Regression for fix-bugs: select_membership used `break` instead of `continue`,
    # so a suspended first membership stopped the search and never reached a later
    # active membership in the same tenant.
    tenant = uuid4()
    principal = uuid4()
    suspended = Membership(uuid4(), tenant, uuid4(), principal, "suspended", 1, None)
    active = Membership(uuid4(), tenant, uuid4(), principal, "active", 2, None)

    context = select_membership([suspended, active], tenant)

    assert context.membership_id == active.id
    assert context.tenant_id == tenant
    assert context.authorization_version == 2


def test_session_is_invalidated_by_user_membership_or_authorization_changes() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    tenant_id, principal_id, membership_id = uuid4(), uuid4(), uuid4()
    membership = Membership(membership_id, tenant_id, uuid4(), principal_id, "active", 2, None)
    session = Session(
        uuid4(), tenant_id, membership_id, principal_id, 2, now + timedelta(hours=1), None
    )

    assert is_session_usable(session, membership, user_status="active", now=now)
    assert not is_session_usable(session, membership, user_status="disabled", now=now)
    assert not is_session_usable(
        session, replace(membership, status="suspended"), user_status="active", now=now
    )
    assert not is_session_usable(
        session, replace(membership, authorization_version=3), user_status="active", now=now
    )
    assert not is_session_usable(
        replace(session, revoked_at=now), membership, user_status="active", now=now
    )


@pytest.mark.asyncio
async def test_me_requires_server_derived_context() -> None:
    app = create_app(Settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


@pytest.mark.asyncio
async def test_me_returns_server_derived_tenant_context() -> None:
    app = create_app(Settings())
    membership = Membership(uuid4(), uuid4(), uuid4(), uuid4(), "active", 2, None)
    context = select_membership([membership], membership.tenant_id)

    class IdentityManagement:
        async def get_me(self, _context):
            return {
                "principal": {
                    "id": str(context.principal_id), "type": "user", "display_name": "U"
                },
                "current_tenant": {
                    "id": str(context.tenant_id), "name": "T", "membership_status": "active"
                },
                "available_tenants": [],
                "coarse_permissions": ["files.read"],
                "authorization_version": context.authorization_version,
            }

    app.state.identity_management = IdentityManagement()

    @app.middleware("http")
    async def inject_context(request, call_next):
        request.state.principal_context = context
        return await call_next(request)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/me")

    assert response.status_code == 200
    assert response.json()["authorization_version"] == 2


def test_application_context_has_no_synthetic_membership() -> None:
    context = PrincipalContext.for_application(uuid4(), uuid4())

    assert context.subject_kind == "application"
    assert context.membership_id is None


@pytest.mark.asyncio
async def test_api_key_resolution_produces_application_subject() -> None:
    tenant_id, application_id, principal_id, key_id = uuid4(), uuid4(), uuid4(), uuid4()

    class ApiKeyService:
        async def authenticate(self, header: str):
            assert header == "S3MP-Key key-id.secret"
            return tenant_id, key_id, {
                "application_id": application_id,
                "application_principal_id": principal_id,
                "application_authorization_version": 7,
                "scopes": ["files.read"],
            }

    class App:
        class State:
            api_key_service = ApiKeyService()

        state = State()

    class Request:
        app = App()

    context = await _resolve_api_key(Request(), "S3MP-Key key-id.secret")

    assert context == PrincipalContext.for_application(
        tenant_id,
        principal_id,
        7,
        application_id=application_id,
        api_key_id=key_id,
        api_key_scopes=frozenset({"files.read"}),
    )
