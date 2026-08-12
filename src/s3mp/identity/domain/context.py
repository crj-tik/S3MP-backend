"""Authenticated principal context passed into tenant-scoped operations."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from s3mp.identity.domain.entities import Membership, Session


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    """Server-derived identity and selected tenant boundary."""

    tenant_id: UUID
    principal_id: UUID
    membership_id: UUID
    authorization_version: int

    def __post_init__(self) -> None:
        if self.tenant_id.int == 0:
            raise ValueError("tenant_id must not be nil")
        if self.principal_id.int == 0:
            raise ValueError("principal_id must not be nil")
        if self.membership_id.int == 0:
            raise ValueError("membership_id must not be nil")
        if self.authorization_version < 1:
            raise ValueError("authorization_version must be positive")


def select_membership(
    memberships: list[Membership], tenant_id: UUID, *, now: datetime | None = None
) -> PrincipalContext:
    """Derive a tenant context only from an active server-known membership."""
    current = now or datetime.now(UTC)
    for membership in memberships:
        if membership.tenant_id != tenant_id:
            continue
        if membership.status != "active":
            continue
        if membership.expires_at is not None and membership.expires_at <= current:
            continue
        return PrincipalContext(
            tenant_id=membership.tenant_id,
            principal_id=membership.principal_id,
            membership_id=membership.id,
            authorization_version=membership.authorization_version,
        )
    raise ValueError("tenant membership is not active")


def is_session_usable(
    session: Session,
    membership: Membership,
    *,
    user_status: str,
    now: datetime | None = None,
) -> bool:
    """Validate every server-side binding before accepting a browser session."""
    current = now or datetime.now(UTC)
    return (
        session.tenant_id == membership.tenant_id
        and session.membership_id == membership.id
        and session.principal_id == membership.principal_id
        and session.authorization_version == membership.authorization_version
        and session.revoked_at is None
        and session.expires_at > current
        and membership.status == "active"
        and (membership.expires_at is None or membership.expires_at > current)
        and user_status == "active"
    )
