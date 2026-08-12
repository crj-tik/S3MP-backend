"""AuthorizedFileCommand: unified command object for all file operations."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from s3mp.authorization.domain.evaluator import (
    Binding,
    Decision,
    evaluate,
    validate_canonical_prefix,
)
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext
from s3mp.storage.domain.policy import canonical_object_key


@dataclass(frozen=True, slots=True)
class AuthorizedFileCommand:
    """Immutable command carrying all context for a file operation.

    The physical key is computed once from the storage space root_prefix
    and the canonical relative key. All downstream operations (authorization,
    persistence, MinIO) must use this command's fields, never raw user input.
    """
    tenant_id: UUID
    acting_principal_id: UUID
    storage_space_id: UUID
    bucket: str
    relative_key: str
    physical_key: str
    action: str
    authorization_version: int
    authorization_evidence: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""
    idempotency_fingerprint: str = ""

    @classmethod
    def create(
        cls,
        ctx: PrincipalContext,
        storage_space: dict[str, Any],
        relative_key: str,
        action: str,
        bindings: list[Binding],
        *,
        request_id: str = "",
        idempotency_key: str = "",
        semantics: dict[str, Any] | None = None,
    ) -> "AuthorizedFileCommand":
        """Create a command from user input, validating and authorizing in one step."""
        # 1. Validate canonical key
        rel = canonical_object_key(relative_key, allow_empty=action == "files.list")
        validate_canonical_prefix(rel)

        # 2. Compute physical key
        root = (storage_space.get("root_prefix") or "").strip("/")
        physical = f"{root}/{rel}" if root else rel

        # 3. Authorize
        now = datetime.now(UTC)
        decision = evaluate(action, bindings, object_key=rel, now=now)

        if decision.decision is not Decision.ALLOW:
            raise ApiError("permission_denied", decision.reason_code, status_code=403)

        evidence = {
            "decision": decision.decision.value,
            "reason": decision.reason_code,
            "sources": [
                {
                    "binding_id": str(source.binding_id) if source.binding_id else None,
                    "effect": source.effect.value,
                    "reason": source.reason_code,
                }
                for source in decision.sources
            ],
            "evaluated_at": now.isoformat(),
            "authorization_version": ctx.authorization_version,
            "subject_kind": ctx.subject_kind,
        }

        # 4. Compute idempotency fingerprint
        fingerprint = ""
        if idempotency_key:
            payload = {
                "tenant_id": str(ctx.tenant_id),
                "principal_id": str(ctx.principal_id),
                "subject_kind": ctx.subject_kind,
                "action": action,
                "storage_space_id": str(storage_space["id"]),
                "relative_key": rel,
                "idempotency_key": idempotency_key,
                "semantics": semantics or {},
            }
            fingerprint = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()

        return cls(
            tenant_id=ctx.tenant_id,
            acting_principal_id=ctx.principal_id,
            storage_space_id=UUID(storage_space["id"]),
            bucket=storage_space.get("bucket", "unknown"),
            relative_key=rel,
            physical_key=physical,
            action=action,
            authorization_version=ctx.authorization_version,
            authorization_evidence=evidence,
            request_id=request_id,
            idempotency_fingerprint=fingerprint,
        )
