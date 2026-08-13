"""Audit fail-close and security monitoring for high-risk operations."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertCategory(StrEnum):
    AUTH_FAILURE = "auth_failure"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    RATE_LIMIT = "rate_limit"
    QUOTA_VIOLATION = "quota_violation"
    AUDIT_FAILURE = "audit_failure"
    ORPHAN_DETECTED = "orphan_detected"
    DELEGATION_VIOLATION = "delegation_violation"


HIGH_RISK_ACTIONS: frozenset[str] = frozenset(
    {
        "role_binding.create",
        "role_binding.revoke",
        "api_key.create",
        "api_key.revoke",
        "user.suspend",
        "user.delete",
        "membership.modify",
        "permission.grant",
        "permission.revoke",
        "object.delete",
        "object.move",
        "storage_connection.modify",
        "quota.modify",
    }
)


@dataclass(frozen=True, slots=True)
class SecurityAlert:
    id: UUID
    tenant_id: UUID
    category: AlertCategory
    severity: AlertSeverity
    message: str
    actor_principal_id: UUID | None
    resource_type: str | None
    resource_id: UUID | None
    details: dict[str, object] = field(default_factory=dict)
    created_at: datetime = datetime.now(UTC)


class AuditFailCloseError(RuntimeError):
    """Raised when a high-risk operation cannot be audited — operation must be aborted."""

    code: str = "audit_fail_close"


class AuditGuard:
    """Ensures high-risk operations are audited before execution, failing closed on audit error."""

    @staticmethod
    def is_high_risk(action: str) -> bool:
        return action in HIGH_RISK_ACTIONS

    @staticmethod
    def require_audit_success(audit_succeeded: bool, action: str, resource_id: str) -> None:
        """Call after attempting to write an audit event for a high-risk action.

        Raises AuditFailCloseError if the audit write failed, preventing the
        operation from proceeding without a durable audit trail.
        """
        if AuditGuard.is_high_risk(action) and not audit_succeeded:
            raise AuditFailCloseError(
                f"Audit write failed for high-risk action '{action}' on {resource_id}; "
                "operation aborted to maintain audit integrity."
            )


class SecurityMonitor:
    """Generates security alerts based on observable system events.

    Designed to be called from application services after detecting anomalies.
    Each method produces a structured SecurityAlert that can be routed to
    logging, metrics, or external alerting channels.
    """

    @staticmethod
    def auth_failure(
        tenant_id: UUID,
        message: str,
        *,
        actor_principal_id: UUID | None = None,
        details: dict[str, object] | None = None,
    ) -> SecurityAlert:
        return SecurityAlert(
            uuid4(),
            tenant_id,
            AlertCategory.AUTH_FAILURE,
            AlertSeverity.WARNING,
            message,
            actor_principal_id,
            None,
            None,
            details or {},
        )

    @staticmethod
    def privilege_escalation_attempt(
        tenant_id: UUID,
        message: str,
        *,
        actor_principal_id: UUID | None = None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
    ) -> SecurityAlert:
        return SecurityAlert(
            uuid4(),
            tenant_id,
            AlertCategory.PRIVILEGE_ESCALATION,
            AlertSeverity.CRITICAL,
            message,
            actor_principal_id,
            resource_type,
            resource_id,
        )

    @staticmethod
    def rate_limit_exceeded(
        tenant_id: UUID,
        message: str,
        *,
        actor_principal_id: UUID | None = None,
    ) -> SecurityAlert:
        return SecurityAlert(
            uuid4(),
            tenant_id,
            AlertCategory.RATE_LIMIT,
            AlertSeverity.WARNING,
            message,
            actor_principal_id,
            None,
            None,
        )

    @staticmethod
    def quota_violation(
        tenant_id: UUID,
        message: str,
        *,
        actor_principal_id: UUID | None = None,
        resource_id: UUID | None = None,
    ) -> SecurityAlert:
        return SecurityAlert(
            uuid4(),
            tenant_id,
            AlertCategory.QUOTA_VIOLATION,
            AlertSeverity.WARNING,
            message,
            actor_principal_id,
            "quota",
            resource_id,
        )

    @staticmethod
    def audit_failure(
        tenant_id: UUID,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> SecurityAlert:
        return SecurityAlert(
            uuid4(),
            tenant_id,
            AlertCategory.AUDIT_FAILURE,
            AlertSeverity.CRITICAL,
            message,
            None,
            None,
            None,
            details or {},
        )

    @staticmethod
    def orphan_detected(
        tenant_id: UUID,
        message: str,
        *,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
    ) -> SecurityAlert:
        return SecurityAlert(
            uuid4(),
            tenant_id,
            AlertCategory.ORPHAN_DETECTED,
            AlertSeverity.CRITICAL,
            message,
            None,
            resource_type,
            resource_id,
        )

    @staticmethod
    def delegation_violation(
        tenant_id: UUID,
        message: str,
        *,
        actor_principal_id: UUID | None = None,
    ) -> SecurityAlert:
        return SecurityAlert(
            uuid4(),
            tenant_id,
            AlertCategory.DELEGATION_VIOLATION,
            AlertSeverity.CRITICAL,
            message,
            actor_principal_id,
            None,
            None,
        )
