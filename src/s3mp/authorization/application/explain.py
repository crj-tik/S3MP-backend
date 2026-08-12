"""Effective-permission and one-shot simulation projections."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from s3mp.authorization.domain.evaluator import (
    AuthorizationDecision,
    Binding,
    Decision,
    DecisionSource,
    evaluate,
)


@dataclass(frozen=True, slots=True)
class EffectivePermission:
    permission: str
    decision: Decision
    reason_code: str
    sources: tuple[DecisionSource, ...]


@dataclass(frozen=True, slots=True)
class EffectivePermissions:
    principal_id: UUID
    authorization_version: int
    evaluated_at: datetime
    permissions: tuple[EffectivePermission, ...]


def explain_permissions(
    principal_id: UUID,
    permissions: list[str],
    bindings: list[Binding],
    *,
    authorization_version: int,
    storage_space_id: UUID | None = None,
    object_key: str = "",
    now: datetime | None = None,
) -> EffectivePermissions:
    evaluated_at = now or datetime.now(UTC)
    results = tuple(
        _to_effective(
            permission,
            evaluate(
                permission,
                bindings,
                storage_space_id=storage_space_id,
                object_key=object_key,
                now=evaluated_at,
            ),
        )
        for permission in sorted(set(permissions))
    )
    return EffectivePermissions(principal_id, authorization_version, evaluated_at, results)


def simulate(
    permission: str,
    bindings: list[Binding],
    *,
    authorization_version: int,
    storage_space_id: UUID | None = None,
    object_key: str = "",
    now: datetime | None = None,
) -> dict[str, object]:
    evaluated_at = now or datetime.now(UTC)
    decision = evaluate(
        permission,
        bindings,
        storage_space_id=storage_space_id,
        object_key=object_key,
        now=evaluated_at,
    )
    return {
        "permission": permission,
        "decision": decision.decision,
        "reason_code": decision.reason_code,
        "authorization_version": authorization_version,
        "evaluated_at": evaluated_at,
        "sources": decision.sources,
    }


def _to_effective(permission: str, decision: AuthorizationDecision) -> EffectivePermission:
    return EffectivePermission(
        permission, decision.decision, decision.reason_code, decision.sources
    )
