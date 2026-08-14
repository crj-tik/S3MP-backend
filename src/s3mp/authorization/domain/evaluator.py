"""Deterministic scoped authorization evaluation."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class Binding:
    id: UUID
    permission: str
    effect: Decision
    canonical_prefix: str | None
    starts_at: datetime
    expires_at: datetime
    reason: str
    storage_space_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class DecisionSource:
    binding_id: UUID | None
    effect: Decision
    reason_code: str


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    decision: Decision
    reason_code: str
    sources: tuple[DecisionSource, ...]


def validate_canonical_prefix(prefix: str) -> str:
    """Validate and return a canonical relative object prefix."""
    if prefix == "":
        return prefix
    if prefix.startswith("/") or "\\" in prefix or "%" in prefix:
        raise ValueError("prefix must be canonical and relative")
    if any(ord(character) < 32 or ord(character) == 127 for character in prefix):
        raise ValueError("prefix must not contain control characters")
    segments = prefix.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError("prefix contains an invalid segment")
    return prefix


def _scope_matches(binding_prefix: str | None, object_key: str) -> bool:
    if binding_prefix is None or binding_prefix == "":
        return True
    return object_key == binding_prefix or object_key.startswith(binding_prefix + "/")


def _as_utc(value: datetime) -> datetime:
    """Normalize persisted timestamps before comparing authorization windows."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def evaluate(
    permission: str,
    bindings: list[Binding],
    *,
    storage_space_id: UUID | None = None,
    object_key: str = "",
    now: datetime | None = None,
) -> AuthorizationDecision:
    """Evaluate active bindings with explicit deny precedence and default deny."""
    current = _as_utc(now or datetime.now(UTC))
    validate_canonical_prefix(object_key)
    matches = [
        binding
        for binding in bindings
        if binding.permission == permission
        and _as_utc(binding.starts_at) <= current < _as_utc(binding.expires_at)
        and (binding.storage_space_id is None or binding.storage_space_id == storage_space_id)
        and _scope_matches(binding.canonical_prefix, object_key)
    ]
    sources = tuple(
        DecisionSource(binding.id, binding.effect, "binding_match") for binding in matches
    )
    if any(binding.effect == Decision.DENY for binding in matches):
        return AuthorizationDecision(Decision.DENY, "explicit_deny", sources)
    if any(binding.effect == Decision.ALLOW for binding in matches):
        return AuthorizationDecision(Decision.ALLOW, "binding_allow", sources)
    return AuthorizationDecision(
        Decision.DENY, "default_deny", (DecisionSource(None, Decision.DENY, "default_deny"),)
    )
