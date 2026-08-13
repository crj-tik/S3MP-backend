"""Shared lifecycle validation for durable file work."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID


class PrincipalState(Protocol):
    async def get_principal(self, tenant_id: UUID, principal_id: UUID) -> dict[str, Any] | None: ...
    async def get_membership_state(
        self, tenant_id: UUID, membership_id: UUID
    ) -> dict[str, Any] | None: ...


class ApiKeyState(Protocol):
    async def get_key_state(self, tenant_id: UUID, key_id: UUID) -> dict[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class DelayedSubject:
    subject_kind: str
    api_key_scopes: frozenset[str] | None


async def validate_delayed_subject(
    *,
    principal_store: PrincipalState | None,
    api_key_store: ApiKeyState | None,
    tenant_id: UUID,
    principal_id: UUID,
    membership_id: str | UUID | None,
    authorization_version: int,
    evidence: dict[str, Any],
    required_permission: str | None = None,
) -> DelayedSubject | None:
    """Validate current subject lifecycle; return no authority on any ambiguity."""
    if principal_store is None:
        return None
    principal = await principal_store.get_principal(tenant_id, principal_id)
    if principal is None or not principal.get("enabled", False):
        return None
    kind = str(evidence.get("subject_kind", "human"))
    if kind != "application":
        if not membership_id:
            return None
        membership = await principal_store.get_membership_state(tenant_id, UUID(str(membership_id)))
        if (
            membership is None
            or membership.get("status") != "active"
            or membership.get("principal_id") != str(principal_id)
            or membership.get("expires_at") is not None
            and membership["expires_at"] <= datetime.now(UTC)
            or int(membership.get("authorization_version", 0)) != authorization_version
        ):
            return None
        return DelayedSubject("human", None)
    key_id = evidence.get("api_key_id")
    if not key_id or api_key_store is None:
        return None
    key = await api_key_store.get_key_state(tenant_id, UUID(str(key_id)))
    if (
        key is None
        or key.get("status") != "active"
        or key.get("application_status") != "active"
        or not key.get("principal_enabled", False)
        or key.get("principal_id") != str(principal_id)
        or key.get("application_id") != evidence.get("application_id")
        or key.get("expires_at") is not None
        and key["expires_at"] <= datetime.now(UTC)
        or int(key.get("application_authorization_version", 0)) < authorization_version
    ):
        return None
    scopes = frozenset(str(scope) for scope in key.get("scopes") or ())
    if required_permission and required_permission not in scopes:
        return None
    return DelayedSubject("application", scopes)
