"""Pure calculations for tenant totals and application reservation pools."""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AllocationSnapshot:
    tenant_limit: int
    tenant_used: int
    tenant_reserved: int
    allocated_application_limit: int
    allocated_application_used: int
    allocated_application_reserved: int

    @property
    def shared_pool_limit(self) -> int:
        return max(self.tenant_limit - self.allocated_application_limit, 0)

    @property
    def shared_pool_used(self) -> int:
        return max(self.tenant_used - self.allocated_application_used, 0)

    @property
    def shared_pool_reserved(self) -> int:
        return max(self.tenant_reserved - self.allocated_application_reserved, 0)

    @property
    def tenant_available(self) -> int:
        return max(self.tenant_limit - self.tenant_used - self.tenant_reserved, 0)

    @property
    def shared_pool_available(self) -> int:
        return max(self.shared_pool_limit - self.shared_pool_used - self.shared_pool_reserved, 0)

    def as_dict(self) -> dict[str, int]:
        return {
            "tenant_limit_bytes": self.tenant_limit,
            "tenant_used_bytes": self.tenant_used,
            "tenant_reserved_bytes": self.tenant_reserved,
            "tenant_available_bytes": self.tenant_available,
            "allocated_application_limit_bytes": self.allocated_application_limit,
            "allocated_application_used_bytes": self.allocated_application_used,
            "allocated_application_reserved_bytes": self.allocated_application_reserved,
            "shared_pool_limit_bytes": self.shared_pool_limit,
            "shared_pool_used_bytes": self.shared_pool_used,
            "shared_pool_reserved_bytes": self.shared_pool_reserved,
            "shared_pool_available_bytes": self.shared_pool_available,
        }


def build_snapshot(tenant: object, applications: Sequence[object]) -> AllocationSnapshot:
    """Build a snapshot from objects exposing the quota ledger attributes."""
    return AllocationSnapshot(
        tenant_limit=max(int(getattr(tenant, "limit_bytes", 0)), 0),
        tenant_used=max(int(getattr(tenant, "used_bytes", 0)), 0),
        tenant_reserved=max(int(getattr(tenant, "reserved_bytes", 0)), 0),
        allocated_application_limit=sum(
            max(int(getattr(row, "limit_bytes", 0)), 0) for row in applications
        ),
        allocated_application_used=sum(
            max(int(getattr(row, "used_bytes", 0)), 0) for row in applications
        ),
        allocated_application_reserved=sum(
            max(int(getattr(row, "reserved_bytes", 0)), 0) for row in applications
        ),
    )
