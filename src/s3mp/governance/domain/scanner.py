"""Governance scanner: detect unbounded grants, unused auth, orphan apps, stale bindings."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class FindingType(StrEnum):
    UNBOUNDED_GRANT = "unbounded_grant"
    LONG_UNUSED_AUTH = "long_unused_auth"
    ORPHAN_APPLICATION = "orphan_application"
    STALE_BINDING = "stale_binding"
    EXPIRED_CREDENTIAL = "expired_credential"


@dataclass(frozen=True, slots=True)
class GovernanceFinding:
    id: UUID
    tenant_id: UUID
    finding_type: FindingType
    severity: FindingSeverity
    resource_type: str
    resource_id: UUID
    summary: str
    detected_at: datetime = datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ScanResult:
    findings: list[GovernanceFinding]
    scanned_at: datetime

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity is FindingSeverity.CRITICAL)

    @property
    def total_count(self) -> int:
        return len(self.findings)


class GovernanceScanner:
    """Stateless scanner that identifies governance risks from raw query results.

    Each method receives a list of dicts (rows) so it can operate on
    ORM or raw SQL results without coupling to a specific query layer.
    """

    DEFAULT_UNBOUNDED_THRESHOLD_DAYS: int = 365
    DEFAULT_UNUSED_THRESHOLD_DAYS: int = 90

    def scan_unbounded_bindings(
        self,
        bindings: list[dict[str, Any]],
        *,
        threshold_days: int | None = None,
    ) -> list[GovernanceFinding]:
        """Detect role bindings with no expiration or expiration too far in the future."""
        threshold = threshold_days or self.DEFAULT_UNBOUNDED_THRESHOLD_DAYS
        cutoff = datetime.now(UTC) + timedelta(days=threshold)
        findings: list[GovernanceFinding] = []

        for row in bindings:
            expires_at = row.get("expires_at")
            if expires_at is None:
                findings.append(
                    GovernanceFinding(
                        uuid4(),
                        row["tenant_id"],
                        FindingType.UNBOUNDED_GRANT,
                        FindingSeverity.HIGH,
                        "role_binding",
                        row["id"],
                        f"RoleBinding {row['id']} has no expiration date",
                    )
                )
            elif isinstance(expires_at, datetime) and expires_at > cutoff:
                findings.append(
                    GovernanceFinding(
                        uuid4(),
                        row["tenant_id"],
                        FindingType.UNBOUNDED_GRANT,
                        FindingSeverity.WARNING,
                        "role_binding",
                        row["id"],
                        f"RoleBinding {row['id']} expires after {threshold_days} days",
                    )
                )
        return findings

    def scan_long_unused_authorizations(
        self,
        api_keys: list[dict[str, Any]],
        *,
        threshold_days: int | None = None,
    ) -> list[GovernanceFinding]:
        """Detect API keys and credentials unused for an extended period."""
        threshold = threshold_days or self.DEFAULT_UNUSED_THRESHOLD_DAYS
        cutoff = datetime.now(UTC) - timedelta(days=threshold)
        findings: list[GovernanceFinding] = []

        for row in api_keys:
            last_used = row.get("last_used_at")
            status = row.get("status", "active")
            if status != "active":
                continue
            if last_used is None:
                findings.append(
                    GovernanceFinding(
                        uuid4(),
                        row["tenant_id"],
                        FindingType.LONG_UNUSED_AUTH,
                        FindingSeverity.WARNING,
                        "api_key",
                        row["id"],
                        f"API key {row.get('key_id', row['id'])} has never been used",
                    )
                )
            elif isinstance(last_used, datetime) and last_used < cutoff:
                findings.append(
                    GovernanceFinding(
                        uuid4(),
                        row["tenant_id"],
                        FindingType.LONG_UNUSED_AUTH,
                        FindingSeverity.INFO,
                        "api_key",
                        row["id"],
                        f"API key {row.get('key_id', row['id'])} unused for {threshold_days}+ days",
                    )
                )
        return findings

    def scan_orphan_applications(
        self,
        applications: list[dict[str, Any]],
        owners: list[dict[str, Any]],
        disabled_principals: set[UUID],
    ) -> list[GovernanceFinding]:
        """Detect applications whose owners are all disabled or missing."""
        app_owners: dict[UUID, set[UUID]] = {}
        for row in owners:
            app_owners.setdefault(row["application_id"], set()).add(row["owner_principal_id"])

        findings: list[GovernanceFinding] = []
        for row in applications:
            app_id = row["id"]
            owner_set = app_owners.get(app_id, set())
            if not owner_set:
                findings.append(
                    GovernanceFinding(
                        uuid4(),
                        row["tenant_id"],
                        FindingType.ORPHAN_APPLICATION,
                        FindingSeverity.CRITICAL,
                        "application",
                        app_id,
                        f"Application {row.get('name', app_id)} has no owners",
                    )
                )
            elif owner_set.issubset(disabled_principals):
                findings.append(
                    GovernanceFinding(
                        uuid4(),
                        row["tenant_id"],
                        FindingType.ORPHAN_APPLICATION,
                        FindingSeverity.CRITICAL,
                        "application",
                        app_id,
                        f"All owners of application {row.get('name', app_id)} are disabled",
                    )
                )
        return findings

    def scan_stale_bindings(
        self,
        bindings: list[dict[str, Any]],
        disabled_principals: set[UUID],
    ) -> list[GovernanceFinding]:
        """Detect role bindings referencing disabled or removed principals."""
        findings: list[GovernanceFinding] = []
        for row in bindings:
            principal_id = row.get("principal_id")
            revoked = row.get("revoked_at")
            if revoked is not None:
                continue  # already revoked, not stale
            if principal_id in disabled_principals:
                findings.append(
                    GovernanceFinding(
                        uuid4(),
                        row["tenant_id"],
                        FindingType.STALE_BINDING,
                        FindingSeverity.HIGH,
                        "role_binding",
                        row["id"],
                        f"RoleBinding {row['id']} references disabled principal {principal_id}",
                    )
                )
        return findings

    def scan_expired_credentials(
        self,
        api_keys: list[dict[str, Any]],
    ) -> list[GovernanceFinding]:
        """Detect API keys that have expired but not been revoked."""
        now = datetime.now(UTC)
        findings: list[GovernanceFinding] = []
        for row in api_keys:
            expires_at = row.get("expires_at")
            if (
                isinstance(expires_at, datetime)
                and expires_at < now
                and row.get("status") == "active"
            ):
                findings.append(
                    GovernanceFinding(
                        uuid4(),
                        row["tenant_id"],
                        FindingType.EXPIRED_CREDENTIAL,
                        FindingSeverity.HIGH,
                        "api_key",
                        row["id"],
                        f"API key {row.get('key_id', row['id'])} expired but still active",
                    )
                )
        return findings

    def full_scan(
        self,
        bindings: list[dict[str, Any]],
        api_keys: list[dict[str, Any]],
        applications: list[dict[str, Any]],
        owners: list[dict[str, Any]],
        disabled_principals: set[UUID],
    ) -> ScanResult:
        findings: list[GovernanceFinding] = []
        findings.extend(self.scan_unbounded_bindings(bindings))
        findings.extend(self.scan_long_unused_authorizations(api_keys))
        findings.extend(self.scan_orphan_applications(applications, owners, disabled_principals))
        findings.extend(self.scan_stale_bindings(bindings, disabled_principals))
        findings.extend(self.scan_expired_credentials(api_keys))
        return ScanResult(findings, datetime.now(UTC))
