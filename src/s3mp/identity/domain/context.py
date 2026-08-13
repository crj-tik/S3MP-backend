"""Authenticated principal context passed into tenant-scoped operations."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from s3mp.identity.domain.entities import Membership, Session


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    """Server-derived identity and selected tenant boundary."""

    tenant_id: UUID
    principal_id: UUID
    membership_id: UUID | None
    authorization_version: int
    subject_kind: Literal["human", "application"] = "human"
    application_id: UUID | None = None
    api_key_id: UUID | None = None
    api_key_scopes: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.tenant_id.int == 0:
            raise ValueError("tenant_id must not be nil")
        if self.principal_id.int == 0:
            raise ValueError("principal_id must not be nil")
        if self.subject_kind not in {"human", "application"}:
            raise ValueError("subject_kind must be human or application")
        if self.subject_kind == "human":
            if self.membership_id is None or self.membership_id.int == 0:
                raise ValueError("human membership_id must not be nil")
        elif self.membership_id is not None:
            raise ValueError("application principals must not have a membership_id")
        if self.subject_kind == "human" and (
            self.application_id is not None or self.api_key_id is not None or self.api_key_scopes is not None
        ):
            raise ValueError("human principals must not carry API key attributes")
        if self.subject_kind == "application" and self.application_id is None:
            raise ValueError("application principals must carry application_id")
        if self.authorization_version < 1:
            raise ValueError("authorization_version must be positive")

    @classmethod
    def for_application(
        cls,
        tenant_id: UUID,
        principal_id: UUID,
        authorization_version: int = 1,
        *,
        application_id: UUID | None = None,
        api_key_id: UUID | None = None,
        api_key_scopes: frozenset[str] | None = None,
    ) -> "PrincipalContext":
        """Create an application principal without fabricating a membership."""
        return cls(
            tenant_id=tenant_id,
            principal_id=principal_id,
            membership_id=None,
            authorization_version=authorization_version,
            subject_kind="application",
            application_id=application_id or principal_id,
            api_key_id=api_key_id,
            api_key_scopes=api_key_scopes,
        )


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
