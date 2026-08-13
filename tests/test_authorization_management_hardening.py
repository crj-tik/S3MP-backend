"""Adversarial service tests for delegated role management."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest

from s3mp.authorization.application.management_service import AuthorizationManagementService
from s3mp.common.errors import ApiError
from s3mp.identity.application.management_ports import AuthorizationManagementStore
from s3mp.identity.domain.context import PrincipalContext


class Store:
    def __init__(self, actor: UUID, role_id: UUID) -> None:
        self.actor, self.role_id = actor, role_id
        self.audits: list[dict[str, object]] = []
        self.updated = False

    async def get_role(self, _tenant: UUID, role_id: UUID) -> dict[str, object] | None:
        if role_id != self.role_id:
            return None
        return {"id": str(role_id), "permissions": ["files.read"], "system": False}

    async def get_principal(self, _tenant: UUID, _principal: UUID) -> dict[str, object]:
        return {"id": "principal"}

    async def bindings_for_principal(
        self, _tenant: UUID, principal: UUID
    ) -> list[dict[str, object]]:
        if principal != self.actor:
            return []
        now = datetime.now(UTC)
        return [
            {
                "id": uuid4(),
                "permission": "files.read",
                "effect": "allow",
                "storage_space_id": None,
                "canonical_prefix": None,
                "starts_at": now - timedelta(minutes=1),
                "expires_at": now + timedelta(hours=2),
                "reason": "delegator authority",
            }
        ]

    async def bindings_for_role(self, _tenant: UUID, _role: UUID) -> list[dict[str, object]]:
        return [{"storage_space_id": None, "canonical_prefix": None}]

    async def record_security_audit(self, *_args: object) -> None:
        self.audits.append(cast(dict[str, object], _args[-1]))

    async def update_role(self, *_args: object) -> dict[str, object]:
        self.updated = True
        return {"id": str(self.role_id), "permissions": ["files.read"]}


def _service(store: Store) -> AuthorizationManagementService:
    return AuthorizationManagementService(
        cast(AuthorizationManagementStore, store),
        frozenset({"files.read", "files.write", "audit.read"}),
        frozenset({"files.read", "files.write"}),
    )


def _context(actor: UUID) -> PrincipalContext:
    return PrincipalContext(uuid4(), actor, uuid4(), 1)


async def test_non_delegable_role_permission_is_rejected() -> None:
    actor, role_id = uuid4(), uuid4()
    store = Store(actor, role_id)
    with pytest.raises(ApiError, match="not delegable"):
        await _service(store).create_role(
            _context(actor),
            SimpleNamespace(name="audit", description=None, permissions=["audit.read"]),
        )


async def test_self_grant_is_rejected_and_redacted_audit_is_recorded() -> None:
    actor, role_id = uuid4(), uuid4()
    store = Store(actor, role_id)
    body = SimpleNamespace(
        role_id=role_id,
        principal_id=actor,
        effect="allow",
        scope=SimpleNamespace(type="tenant", storage_space_id=None, canonical_prefix=None),
        reason="attempt",
        starts_at=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    with pytest.raises(ApiError, match="Self-grants"):
        await _service(store).create_role_binding(_context(actor), body)
    assert store.audits == [{"reason_code": "self_grant"}]


async def test_bound_role_cannot_gain_permission_not_held_by_delegator() -> None:
    actor, role_id = uuid4(), uuid4()
    store = Store(actor, role_id)
    body = SimpleNamespace(
        name=None, description="attempt", permissions=["files.read", "files.write"]
    )
    with pytest.raises(ApiError, match="Delegation exceeds authority"):
        await _service(store).update_role(_context(actor), role_id, body)
    assert not store.updated
    assert store.audits == [{"reason_code": "permission_or_scope_exceeds_authority"}]


async def test_system_role_rejects_non_permission_edits() -> None:
    actor, role_id = uuid4(), uuid4()

    class SystemRoleStore(Store):
        async def get_role(self, _tenant: UUID, _role: UUID) -> dict[str, object] | None:
            return {"id": str(role_id), "permissions": ["files.read"], "system": True}

    store = SystemRoleStore(actor, role_id)
    with pytest.raises(ApiError, match="immutable"):
        await _service(store).update_role(
            _context(actor),
            role_id,
            SimpleNamespace(name="renamed", description=None, permissions=None),
        )
    assert not store.updated


async def test_binding_expiry_cannot_exceed_delegator_expiry() -> None:
    actor, role_id = uuid4(), uuid4()
    store = Store(actor, role_id)
    body = SimpleNamespace(
        role_id=role_id,
        principal_id=uuid4(),
        effect="allow",
        scope=SimpleNamespace(
            type="storage_space", storage_space_id=uuid4(), canonical_prefix=None
        ),
        reason="temporary access",
        starts_at=None,
        expires_at=datetime.now(UTC) + timedelta(hours=3),
    )

    async def space_exists(_tenant: UUID, _space: UUID) -> bool:
        return True

    store.storage_space_exists = space_exists  # type: ignore[attr-defined]
    with pytest.raises(ApiError, match="expiry exceeds authority"):
        await _service(store).create_role_binding(_context(actor), body)
    assert store.audits == [{"reason_code": "expiry_exceeds_authority"}]
