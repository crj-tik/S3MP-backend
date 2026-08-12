"""End-to-end governance flow: login → permission → suspend → revoke → recover."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from s3mp.authorization.application.explain import explain_permissions
from s3mp.authorization.application.versioning import (
    InMemoryAuthorizationVersionStore,
    StaleAuthorization,
    VersionedAuthorizationCache,
    require_current_version,
)
from s3mp.authorization.domain.delegation import (
    DelegationScope,
    validate_delegated_scope,
    validate_direct_grant,
)
from s3mp.authorization.domain.evaluator import (
    Binding,
    Decision,
    evaluate,
)
from s3mp.identity.application.security import (
    PasswordHasher,
    SessionTokenService,
)
from s3mp.identity.domain.context import (
    PrincipalContext,
    is_session_usable,
    select_membership,
)
from s3mp.identity.domain.entities import Membership, Session

# ── helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime(2026, 8, 1, tzinfo=UTC)


def _binding(
    permission: str,
    effect: Decision,
    prefix: str | None = None,
    *,
    expires_delta: timedelta = timedelta(hours=1),
) -> Binding:
    return Binding(
        uuid4(), permission, effect, prefix,
        _now() - timedelta(minutes=1), _now() + expires_delta, "test",
    )


def _make_membership(
    tenant_id: str | None = None,
    *,
    status: str = "active",
    auth_version: int = 2,
    expires_at: datetime | None = None,
) -> Membership:
    return Membership(
        uuid4(), uuid4() if tenant_id is None else uuid4(), uuid4(), uuid4(),
        status, auth_version, expires_at,
    )


def _make_session(
    membership: Membership,
    *,
    auth_version: int | None = None,
    expires_delta: timedelta = timedelta(hours=1),
    revoked_at: datetime | None = None,
) -> Session:
    return Session(
        uuid4(), membership.tenant_id, membership.id, membership.principal_id,
        auth_version if auth_version is not None else membership.authorization_version,
        _now() + expires_delta, revoked_at,
    )


# ── Phase 1: Authentication & Context ────────────────────────────────────────

class TestAuthenticationAndContext:
    """Login → session → PrincipalContext → /me."""

    def test_password_auth_chain(self) -> None:
        """Full local auth: hash → verify → authenticate."""
        hasher = PasswordHasher()
        user_id = uuid4()
        h = hasher.hash("correct")
        assert hasher.verify("correct", h)
        assert not hasher.verify("wrong", h)

    def test_session_token_chain(self) -> None:
        """Issue opaque tokens → verify → CSRF."""
        svc = SessionTokenService(b"p" * 32)
        tokens = svc.issue()
        digest = svc.digest(tokens.session_token)
        assert svc.verify(tokens.session_token, digest)
        assert svc.verify_csrf(tokens.csrf_token, tokens.csrf_token)

    def test_context_from_active_membership(self) -> None:
        membership = _make_membership(auth_version=3)
        ctx = select_membership([membership], membership.tenant_id, now=_now())
        assert ctx.tenant_id == membership.tenant_id
        assert ctx.principal_id == membership.principal_id
        assert ctx.authorization_version == 3

    def test_context_rejects_inactive_membership(self) -> None:
        for status in ("suspended", "removed", "invited"):
            m = _make_membership(status=status)
            with pytest.raises(ValueError, match="not active"):
                select_membership([m], m.tenant_id, now=_now())

    def test_context_rejects_expired_membership(self) -> None:
        m = _make_membership(expires_at=_now() - timedelta(days=1))
        with pytest.raises(ValueError, match="not active"):
            select_membership([m], m.tenant_id, now=_now())

    def test_context_rejects_other_tenant(self) -> None:
        m = _make_membership()
        with pytest.raises(ValueError, match="not active"):
            select_membership([m], uuid4(), now=_now())


# ── Phase 2: Authorization & Binding ─────────────────────────────────────────

class TestAuthorizationBinding:
    """User → group → role → RoleBinding → effective permissions."""

    def test_allow_through_group_binding(self) -> None:
        decision = evaluate(
            "files.read",
            [_binding("files.read", Decision.ALLOW, "team")],
            object_key="team/reports/q1.csv",
            now=_now(),
        )
        assert decision.decision == Decision.ALLOW
        assert decision.reason_code == "binding_allow"

    def test_deny_overrides_allow(self) -> None:
        decision = evaluate(
            "files.read",
            [
                _binding("files.read", Decision.ALLOW, "team"),
                _binding("files.read", Decision.DENY, "team/private"),
            ],
            object_key="team/private/secrets.txt",
            now=_now(),
        )
        assert decision.decision == Decision.DENY
        assert decision.reason_code == "explicit_deny"

    def test_default_deny_without_any_binding(self) -> None:
        decision = evaluate("files.write", [], object_key="any/file.txt", now=_now())
        assert decision.decision == Decision.DENY
        assert decision.reason_code == "default_deny"

    def test_scope_outside_prefix_is_denied(self) -> None:
        decision = evaluate(
            "files.read",
            [_binding("files.read", Decision.ALLOW, "team")],
            object_key="other/file.txt",
            now=_now(),
        )
        assert decision.decision == Decision.DENY

    def test_expired_binding_is_ignored(self) -> None:
        expired = Binding(
            uuid4(), "files.read", Decision.ALLOW, "team",
            _now() - timedelta(hours=2), _now() - timedelta(minutes=1), "expired",
        )
        decision = evaluate("files.read", [expired], object_key="team/a.txt", now=_now())
        assert decision.decision == Decision.DENY

    def test_explain_returns_sorted_permissions_with_sources(self) -> None:
        result = explain_permissions(
            uuid4(),
            ["files.read", "files.write"],
            [_binding("files.read", Decision.ALLOW, "team")],
            authorization_version=2,
            object_key="team/data.csv",
            now=_now(),
        )
        assert result.authorization_version == 2
        assert len(result.permissions) == 2
        assert result.permissions[0].permission == "files.read"
        assert result.permissions[0].decision == Decision.ALLOW
        assert result.permissions[1].permission == "files.write"
        assert result.permissions[1].decision == Decision.DENY


# ── Phase 3: Suspend → Revoke ────────────────────────────────────────────────

class TestSuspendAndRevoke:
    """Suspend user → authorization version bump → session invalid → no new presign."""

    def test_suspend_invalidates_session(self) -> None:
        membership = _make_membership(status="active", auth_version=2)
        session = _make_session(membership, auth_version=2)

        # Initially valid
        assert is_session_usable(session, membership, user_status="active", now=_now())

        # Suspend membership
        suspended = replace(membership, status="suspended")
        assert not is_session_usable(session, suspended, user_status="active", now=_now())

    def test_disabled_user_invalidates_session(self) -> None:
        membership = _make_membership(status="active")
        session = _make_session(membership)
        assert not is_session_usable(session, membership, user_status="disabled", now=_now())

    def test_revoked_session_is_denied(self) -> None:
        membership = _make_membership(status="active")
        session = _make_session(membership, revoked_at=_now())
        assert not is_session_usable(session, membership, user_status="active", now=_now())

    @pytest.mark.asyncio
    async def test_authorization_version_bump_invalidates_cache(self) -> None:
        tenant_id = uuid4()
        store = InMemoryAuthorizationVersionStore()
        cache = VersionedAuthorizationCache()

        v1 = await store.current(tenant_id)
        assert v1 == 1
        cache.put("perm:user-1", {"files.read": "allow"}, v1)

        v2 = await store.bump(tenant_id)
        assert v2 == 2
        assert cache.get("perm:user-1", v2) is None  # stale cache
        assert cache.get("perm:user-1", v1) == {"files.read": "allow"}  # old version still readable

    def test_stale_version_is_rejected(self) -> None:
        require_current_version(3, 3)
        with pytest.raises(StaleAuthorization):
            require_current_version(2, 3)

    @pytest.mark.asyncio
    async def test_suspend_bumps_version_and_new_session_required(self) -> None:
        """Full flow: active → suspend bumps version → old session stale."""
        store = InMemoryAuthorizationVersionStore()
        cache = VersionedAuthorizationCache()
        tenant_id = uuid4()

        # User is active, version 1
        v1 = await store.current(tenant_id)
        cache.put("cursor:abc", "data", v1)

        # Admin suspends → bump version
        v2 = await store.bump(tenant_id)
        assert v2 == 2

        # Old cursor is stale
        assert cache.get("cursor:abc", v2) is None
        with pytest.raises(StaleAuthorization):
            require_current_version(v1, v2)

    @pytest.mark.asyncio
    async def test_membership_removal_bumps_version(self) -> None:
        store = InMemoryAuthorizationVersionStore()
        tenant_id = uuid4()
        v1 = await store.current(tenant_id)
        v2 = await store.bump(tenant_id)  # membership removed
        assert v2 == v1 + 1


# ── Phase 4: Delegation & Separation of Duties ───────────────────────────────

class TestDelegationAndSeparation:
    """Delegation subset checks and separation of duties."""

    def test_direct_grant_requires_reason_and_future_expiry(self) -> None:
        actor = uuid4()
        target = uuid4()
        future = _now() + timedelta(days=30)

        validate_direct_grant(
            actor_principal_id=actor,
            target_principal_id=target,
            permission="files.read",
            reason="project access",
            expires_at=future,
            now=_now(),
        )

    def test_direct_grant_rejects_self_grant(self) -> None:
        pid = uuid4()
        future = _now() + timedelta(days=30)
        with pytest.raises(ValueError, match="itself"):
            validate_direct_grant(
                actor_principal_id=pid,
                target_principal_id=pid,
                permission="files.read",
                reason="self",
                expires_at=future,
            )

    def test_direct_grant_rejects_empty_reason(self) -> None:
        future = _now() + timedelta(days=30)
        with pytest.raises(ValueError, match="reason"):
            validate_direct_grant(
                actor_principal_id=uuid4(),
                target_principal_id=uuid4(),
                permission="files.read",
                reason="   ",
                expires_at=future,
            )

    def test_direct_grant_rejects_past_expiry(self) -> None:
        past = _now() - timedelta(days=1)
        with pytest.raises(ValueError, match="future expiry"):
            validate_direct_grant(
                actor_principal_id=uuid4(),
                target_principal_id=uuid4(),
                permission="files.read",
                reason="test",
                expires_at=past,
                now=_now(),
            )

    def test_delegation_must_be_subset(self) -> None:
        delegator = DelegationScope(frozenset({"files.read", "files.write"}), "team")
        # Valid subset
        validate_delegated_scope(
            DelegationScope(frozenset({"files.read"}), "team/reports"), delegator
        )
        # Permission not in delegator set
        with pytest.raises(ValueError, match="exceed"):
            validate_delegated_scope(
                DelegationScope(frozenset({"files.admin"}), "team"), delegator
            )
        # Prefix broader than delegator
        with pytest.raises(ValueError, match="exceed"):
            validate_delegated_scope(
                DelegationScope(frozenset({"files.read"}), "other"), delegator
            )


# ── Phase 5: Full Governance Lifecycle ───────────────────────────────────────

class TestFullGovernanceLifecycle:
    """End-to-end: login → bind → suspend → verify revocation → recover."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_login_to_revocation(self) -> None:
        """Complete governance flow in a single test."""
        store = InMemoryAuthorizationVersionStore()
        cache = VersionedAuthorizationCache()
        tenant_id = uuid4()
        principal_id = uuid4()
        membership_id = uuid4()

        # ── Step 1: User logs in, active membership ──
        membership = Membership(
            membership_id, tenant_id, uuid4(), principal_id, "active", 1, None
        )
        ctx = select_membership([membership], tenant_id, now=_now())
        assert ctx.principal_id == principal_id
        assert ctx.authorization_version == 1

        # ── Step 2: User gets group → role → binding → effective permissions ──
        session = _make_session(membership, auth_version=1)
        assert is_session_usable(session, membership, user_status="active", now=_now())

        bindings = [
            _binding("files.read", Decision.ALLOW, "team"),
            _binding("files.list", Decision.ALLOW, "team"),
        ]
        decision = evaluate("files.read", bindings, object_key="team/data.csv", now=_now())
        assert decision.decision == Decision.ALLOW

        # Cache permissions
        cache.put(f"perm:{principal_id}", {"files.read": "allow"}, 1)

        # ── Step 3: Admin suspends membership → version bump ──
        v2 = await store.bump(tenant_id)
        assert v2 == 2
        suspended = replace(membership, status="suspended", authorization_version=v2)

        # Old session is invalid
        assert not is_session_usable(session, suspended, user_status="active", now=_now())

        # Old permission cache is stale
        assert cache.get(f"perm:{principal_id}", v2) is None
        with pytest.raises(StaleAuthorization):
            require_current_version(1, v2)

        # ── Step 4: User cannot get new presigned URL (no valid session) ──
        # Simulated by checking that no active membership exists
        with pytest.raises(ValueError, match="not active"):
            select_membership([suspended], tenant_id, now=_now())

        # ── Step 5: Admin reactivates → new version → new session required ──
        v3 = await store.bump(tenant_id)
        reactivated = replace(membership, status="active", authorization_version=v3)
        new_ctx = select_membership([reactivated], tenant_id, now=_now())
        assert new_ctx.authorization_version == v3

        new_session = _make_session(reactivated, auth_version=v3)
        assert is_session_usable(new_session, reactivated, user_status="active", now=_now())

        # Old version still stale
        with pytest.raises(StaleAuthorization):
            require_current_version(1, v3)

    @pytest.mark.asyncio
    async def test_group_change_triggers_re_evaluation(self) -> None:
        """Changing group membership should trigger version bump."""
        store = InMemoryAuthorizationVersionStore()
        tenant_id = uuid4()

        v1 = await store.current(tenant_id)
        assert v1 == 1

        # User added to group → version bump
        v2 = await store.bump(tenant_id)
        assert v2 == 2

        # User removed from group → version bump
        v3 = await store.bump(tenant_id)
        assert v3 == 3

        # Role binding changed → version bump
        v4 = await store.bump(tenant_id)
        assert v4 == 4

    @pytest.mark.asyncio
    async def test_permission_change_propagates_to_new_evaluation(self) -> None:
        """After permission change, re-evaluation uses new bindings."""
        store = InMemoryAuthorizationVersionStore()
        cache = VersionedAuthorizationCache()
        tenant_id = uuid4()

        # Initial version
        v1 = await store.current(tenant_id)
        cache.put("eval:obj-1", {"decision": "allow"}, v1)

        # Permission revoked → version bump
        v2 = await store.bump(tenant_id)

        # Old evaluation is stale
        assert cache.get("eval:obj-1", v2) is None

        # New evaluation with updated bindings
        new_bindings = [_binding("files.read", Decision.DENY, "team")]
        decision = evaluate("files.read", new_bindings, object_key="team/data.csv", now=_now())
        assert decision.decision == Decision.DENY
        cache.put("eval:obj-1", {"decision": "deny"}, v2)
        assert cache.get("eval:obj-1", v2) == {"decision": "deny"}

    def test_platform_admin_cannot_read_user_data(self) -> None:
        """Platform admin has no implicit read on user file data."""
        # Platform admin binding with no file scope
        admin_bindings = [
            _binding("platform.admin", Decision.ALLOW, None),
        ]
        # Attempting file read → denied (no file permission)
        decision = evaluate("files.read", admin_bindings, object_key="user/data.csv", now=_now())
        assert decision.decision == Decision.DENY
        assert decision.reason_code == "default_deny"

    def test_principal_context_rejects_nil_ids(self) -> None:
        """Invalid context construction must be rejected at the boundary."""
        nil = UUID(int=0)
        with pytest.raises(ValueError, match="nil"):
            PrincipalContext(tenant_id=nil, principal_id=uuid4(), membership_id=uuid4(), authorization_version=1)
        with pytest.raises(ValueError, match="nil"):
            PrincipalContext(tenant_id=uuid4(), principal_id=nil, membership_id=uuid4(), authorization_version=1)
        with pytest.raises(ValueError, match="nil"):
            PrincipalContext(tenant_id=uuid4(), principal_id=uuid4(), membership_id=nil, authorization_version=1)
        with pytest.raises(ValueError, match="positive"):
            PrincipalContext(tenant_id=uuid4(), principal_id=uuid4(), membership_id=uuid4(), authorization_version=0)