"""Append-only audit event construction without credentials or full URLs."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: UUID
    tenant_id: UUID
    actor_principal_id: UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    details: dict[str, object]
    occurred_at: datetime


class AuditWriter:
    def create(
        self,
        tenant_id: UUID,
        action: str,
        resource_type: str,
        *,
        actor_principal_id: UUID | None = None,
        resource_id: str | None = None,
        details: dict[str, object] | None = None,
    ) -> AuditEvent:
        safe = {
            key: value
            for key, value in (details or {}).items()
            if key not in {"url", "secret", "credential", "authorization"}
        }
        return AuditEvent(
            uuid4(),
            tenant_id,
            actor_principal_id,
            action,
            resource_type,
            resource_id,
            safe,
            datetime.now(UTC),
        )

    @staticmethod
    def fingerprint(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def serialize(event: AuditEvent) -> str:
        return json.dumps(
            {"id": str(event.id), "tenant_id": str(event.tenant_id), "action": event.action},
            sort_keys=True,
        )
