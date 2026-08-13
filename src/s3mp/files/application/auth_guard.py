"""File authorization guard: enforce canonical key, ownership, and RBAC."""

from datetime import UTC, datetime
from typing import Any

from s3mp.authorization.domain.evaluator import (
    Binding,
    Decision,
    evaluate,
    validate_canonical_prefix,
)
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext
from s3mp.storage.domain.policy import canonical_object_key


class FileAuthGuard:
    """Lightweight guard that enforces file-level authorization rules.

    Bindings are resolved by the application service and passed in.
    """

    @staticmethod
    def validate_canonical_key(object_key: str) -> str:
        """Validate that the object key is canonical (no traversal, no unsafe chars)."""
        return canonical_object_key(object_key)

    @staticmethod
    def validate_canonical_prefix(prefix: str) -> str:
        """Validate that the directory prefix is canonical."""
        validate_canonical_prefix(prefix)
        return prefix

    @staticmethod
    def check_ownership(record: dict[str, Any], ctx: PrincipalContext) -> None:
        """Verify that the record's principal_id matches the current context."""
        rid = record.get("principal_id")
        if not rid or str(rid) != str(ctx.principal_id):
            raise ApiError("permission_denied", "Not authorized for this resource", status_code=403)

    @staticmethod
    def check_tenant(record: dict[str, Any], ctx: PrincipalContext) -> None:
        """Verify that the record belongs to the current tenant."""
        if str(record.get("tenant_id")) != str(ctx.tenant_id):
            raise ApiError("resource_not_found", "Not found", status_code=404)

    @staticmethod
    def evaluate_access(
        permission: str,
        bindings: list[Binding],
        object_key: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Evaluate whether the current principal has the requested permission."""
        decision = evaluate(
            permission,
            bindings,
            object_key=object_key,
            now=now or datetime.now(UTC),
        )
        if decision.decision is not Decision.ALLOW:
            raise ApiError("permission_denied", decision.reason_code, status_code=403)
        return True
