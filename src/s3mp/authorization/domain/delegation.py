"""Delegation and direct-grant safety checks."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from s3mp.authorization.domain.evaluator import validate_canonical_prefix


@dataclass(frozen=True, slots=True)
class DelegationScope:
    permissions: frozenset[str]
    canonical_prefix: str | None = None


def _prefix_contains(parent: str | None, child: str | None) -> bool:
    if parent is None or parent == "":
        return True
    if child is None:
        return False
    return child == parent or child.startswith(parent + "/")


def validate_direct_grant(
    *,
    actor_principal_id: UUID,
    target_principal_id: UUID,
    permission: str,
    reason: str,
    expires_at: datetime,
    now: datetime | None = None,
) -> None:
    if actor_principal_id == target_principal_id:
        raise ValueError("a principal must not grant authority to itself")
    if not reason.strip():
        raise ValueError("direct grants require a reason")
    current = now or datetime.now(UTC)
    if expires_at <= current:
        raise ValueError("direct grants require a future expiry")
    if not permission or permission != permission.strip():
        raise ValueError("permission must be canonical")


def validate_delegated_scope(grant: DelegationScope, delegator: DelegationScope) -> None:
    validate_canonical_prefix(grant.canonical_prefix or "")
    if not grant.permissions.issubset(delegator.permissions):
        raise ValueError("delegated permissions exceed the delegator subset")
    if not _prefix_contains(delegator.canonical_prefix, grant.canonical_prefix):
        raise ValueError("delegated prefix exceeds the delegator scope")
