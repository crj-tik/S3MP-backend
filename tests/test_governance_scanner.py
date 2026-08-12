"""Governance scanner tests for unbounded auth, orphans, and stale bindings."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from s3mp.governance.domain.scanner import (
    FindingSeverity,
    FindingType,
    GovernanceScanner,
)


class TestScanUnboundedBindings:
    def test_no_expiration_is_high(self) -> None:
        scanner = GovernanceScanner()
        bindings = [{"id": uuid4(), "tenant_id": uuid4(), "expires_at": None}]
        findings = scanner.scan_unbounded_bindings(bindings)
        assert len(findings) == 1
        assert findings[0].finding_type is FindingType.UNBOUNDED_GRANT
        assert findings[0].severity is FindingSeverity.HIGH

    def test_far_future_expiration_is_warning(self) -> None:
        scanner = GovernanceScanner()
        far = datetime.now(UTC) + timedelta(days=400)
        bindings = [{"id": uuid4(), "tenant_id": uuid4(), "expires_at": far}]
        findings = scanner.scan_unbounded_bindings(bindings, threshold_days=365)
        assert len(findings) == 1
        assert findings[0].severity is FindingSeverity.WARNING

    def test_near_future_expiration_not_flagged(self) -> None:
        scanner = GovernanceScanner()
        near = datetime.now(UTC) + timedelta(days=30)
        bindings = [{"id": uuid4(), "tenant_id": uuid4(), "expires_at": near}]
        findings = scanner.scan_unbounded_bindings(bindings, threshold_days=365)
        assert len(findings) == 0


class TestScanLongUnused:
    def test_never_used_key_is_warning(self) -> None:
        scanner = GovernanceScanner()
        keys = [
            {"id": uuid4(), "tenant_id": uuid4(), "key_id": "k1", "status": "active",
             "last_used_at": None}
        ]
        findings = scanner.scan_long_unused_authorizations(keys, threshold_days=90)
        assert len(findings) == 1
        assert findings[0].severity is FindingSeverity.WARNING

    def test_long_unused_is_info(self) -> None:
        scanner = GovernanceScanner()
        old = datetime.now(UTC) - timedelta(days=120)
        keys = [
            {"id": uuid4(), "tenant_id": uuid4(), "key_id": "k1", "status": "active",
             "last_used_at": old}
        ]
        findings = scanner.scan_long_unused_authorizations(keys, threshold_days=90)
        assert len(findings) == 1
        assert findings[0].severity is FindingSeverity.INFO

    def test_recently_used_key_not_flagged(self) -> None:
        scanner = GovernanceScanner()
        recent = datetime.now(UTC) - timedelta(days=10)
        keys = [
            {"id": uuid4(), "tenant_id": uuid4(), "key_id": "k1", "status": "active",
             "last_used_at": recent}
        ]
        findings = scanner.scan_long_unused_authorizations(keys, threshold_days=90)
        assert len(findings) == 0


class TestScanOrphanApplications:
    def test_no_owners_is_critical(self) -> None:
        scanner = GovernanceScanner()
        apps = [{"id": uuid4(), "tenant_id": uuid4(), "name": "orphan"}]
        owners: list[dict] = []
        findings = scanner.scan_orphan_applications(apps, owners, set())
        assert len(findings) == 1
        assert findings[0].severity is FindingSeverity.CRITICAL

    def test_all_owners_disabled_is_critical(self) -> None:
        scanner = GovernanceScanner()
        app_id = uuid4()
        disabled = uuid4()
        apps = [{"id": app_id, "tenant_id": uuid4(), "name": "semi-orphan"}]
        owners = [{"application_id": app_id, "owner_principal_id": disabled}]
        findings = scanner.scan_orphan_applications(apps, owners, {disabled})
        assert len(findings) == 1
        assert findings[0].severity is FindingSeverity.CRITICAL

    def test_valid_owner_not_flagged(self) -> None:
        scanner = GovernanceScanner()
        app_id = uuid4()
        owner_id = uuid4()
        apps = [{"id": app_id, "tenant_id": uuid4(), "name": "ok"}]
        owners = [{"application_id": app_id, "owner_principal_id": owner_id}]
        findings = scanner.scan_orphan_applications(apps, owners, set())
        assert len(findings) == 0


class TestScanStaleBindings:
    def test_disabled_principal_binding_is_high(self) -> None:
        scanner = GovernanceScanner()
        disabled = uuid4()
        bindings = [
            {"id": uuid4(), "tenant_id": uuid4(), "principal_id": disabled, "revoked_at": None}
        ]
        findings = scanner.scan_stale_bindings(bindings, {disabled})
        assert len(findings) == 1
        assert findings[0].severity is FindingSeverity.HIGH

    def test_already_revoked_binding_not_flagged(self) -> None:
        scanner = GovernanceScanner()
        disabled = uuid4()
        bindings = [
            {"id": uuid4(), "tenant_id": uuid4(), "principal_id": disabled,
             "revoked_at": datetime.now(UTC)}
        ]
        findings = scanner.scan_stale_bindings(bindings, {disabled})
        assert len(findings) == 0


class TestScanExpiredCredentials:
    def test_expired_active_key_is_high(self) -> None:
        scanner = GovernanceScanner()
        past = datetime.now(UTC) - timedelta(days=1)
        keys = [
            {"id": uuid4(), "tenant_id": uuid4(), "key_id": "k1", "status": "active",
             "expires_at": past}
        ]
        findings = scanner.scan_expired_credentials(keys)
        assert len(findings) == 1
        assert findings[0].severity is FindingSeverity.HIGH

    def test_future_expiry_not_flagged(self) -> None:
        scanner = GovernanceScanner()
        future = datetime.now(UTC) + timedelta(days=30)
        keys = [
            {"id": uuid4(), "tenant_id": uuid4(), "key_id": "k1", "status": "active",
             "expires_at": future}
        ]
        findings = scanner.scan_expired_credentials(keys)
        assert len(findings) == 0


class TestFullScan:
    def test_aggregates_all_findings(self) -> None:
        scanner = GovernanceScanner()
        result = scanner.full_scan(
            bindings=[{"id": uuid4(), "tenant_id": uuid4(), "expires_at": None}],
            api_keys=[],
            applications=[],
            owners=[],
            disabled_principals=set(),
        )
        assert result.total_count == 1
        assert result.critical_count == 0