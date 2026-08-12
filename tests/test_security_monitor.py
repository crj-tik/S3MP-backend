"""Security monitor and audit guard tests."""

from uuid import uuid4

import pytest

from s3mp.governance.domain.security_monitor import (
    AlertCategory,
    AlertSeverity,
    AuditFailCloseError,
    AuditGuard,
    SecurityMonitor,
)


class TestAuditGuard:
    def test_high_risk_action_identified(self) -> None:
        assert AuditGuard.is_high_risk("role_binding.create") is True
        assert AuditGuard.is_high_risk("user.suspend") is True
        assert AuditGuard.is_high_risk("api_key.revoke") is True

    def test_low_risk_action_not_flagged(self) -> None:
        assert AuditGuard.is_high_risk("file.list") is False
        assert AuditGuard.is_high_risk("object.head") is False

    def test_fail_close_on_high_risk_audit_failure(self) -> None:
        with pytest.raises(AuditFailCloseError, match="audit integrity"):
            AuditGuard.require_audit_success(False, "user.suspend", "user-1")

    def test_no_error_on_low_risk_audit_failure(self) -> None:
        AuditGuard.require_audit_success(False, "file.list", "obj-1")

    def test_no_error_on_successful_audit(self) -> None:
        AuditGuard.require_audit_success(True, "user.suspend", "user-1")


class TestSecurityMonitor:
    def test_auth_failure_alert(self) -> None:
        alert = SecurityMonitor.auth_failure(uuid4(), "bad password")
        assert alert.category is AlertCategory.AUTH_FAILURE
        assert alert.severity is AlertSeverity.WARNING

    def test_privilege_escalation_is_critical(self) -> None:
        alert = SecurityMonitor.privilege_escalation_attempt(uuid4(), "delegation out of scope")
        assert alert.category is AlertCategory.PRIVILEGE_ESCALATION
        assert alert.severity is AlertSeverity.CRITICAL

    def test_audit_failure_is_critical(self) -> None:
        alert = SecurityMonitor.audit_failure(uuid4(), "audit write failed")
        assert alert.severity is AlertSeverity.CRITICAL

    def test_orphan_detected_is_critical(self) -> None:
        alert = SecurityMonitor.orphan_detected(uuid4(), "app has no owners")
        assert alert.severity is AlertSeverity.CRITICAL

    def test_rate_limit_is_warning(self) -> None:
        alert = SecurityMonitor.rate_limit_exceeded(uuid4(), "too many requests")
        assert alert.severity is AlertSeverity.WARNING

    def test_delegation_violation_is_critical(self) -> None:
        alert = SecurityMonitor.delegation_violation(uuid4(), "grant beyond own scope")
        assert alert.severity is AlertSeverity.CRITICAL