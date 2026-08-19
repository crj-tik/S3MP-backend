from types import SimpleNamespace
from typing import Any, cast

import pytest

from s3mp.governance.domain.allocation import build_snapshot
from s3mp.governance.infrastructure.models import QuotaModel, QuotaReservationModel


def test_shared_pool_is_tenant_total_minus_reserved_applications() -> None:
    tenant = SimpleNamespace(limit_bytes=300, used_bytes=120, reserved_bytes=20)
    applications = [
        SimpleNamespace(limit_bytes=100, used_bytes=70, reserved_bytes=10),
        SimpleNamespace(limit_bytes=50, used_bytes=20, reserved_bytes=0),
    ]

    snapshot = build_snapshot(tenant, applications)

    assert snapshot.shared_pool_limit == 150
    assert snapshot.shared_pool_used == 30
    assert snapshot.shared_pool_reserved == 10
    assert snapshot.shared_pool_available == 110
    assert snapshot.tenant_available == 160


def test_negative_ledger_values_are_clamped_for_safe_reporting() -> None:
    snapshot = build_snapshot(
        SimpleNamespace(limit_bytes=100, used_bytes=-1, reserved_bytes=-2),
        [SimpleNamespace(limit_bytes=-10, used_bytes=-3, reserved_bytes=-4)],
    )

    assert snapshot.as_dict()["shared_pool_limit_bytes"] == 100
    assert snapshot.as_dict()["shared_pool_available_bytes"] == 100


@pytest.mark.parametrize(
    ("tenant", "applications", "expected"),
    [
        (SimpleNamespace(limit_bytes=100, used_bytes=0, reserved_bytes=0), [], 100),
        (
            SimpleNamespace(limit_bytes=100, used_bytes=50, reserved_bytes=10),
            [SimpleNamespace(limit_bytes=100, used_bytes=50, reserved_bytes=10)],
            0,
        ),
    ],
)
def test_shared_pool_available(tenant: object, applications: list[object], expected: int) -> None:
    assert build_snapshot(tenant, applications).shared_pool_available == expected


def test_persistent_quota_constraints_cover_allocation_states() -> None:
    quota_table = cast(Any, QuotaModel.__table__)
    reservation_table = cast(Any, QuotaReservationModel.__table__)
    names = {constraint.name for constraint in quota_table.constraints}
    assert any(name.endswith("ck_quota_allocation_mode") for name in names)
    assert any(name.endswith("ck_quota_status") for name in names)
    indexes = {index.name for index in quota_table.indexes}
    assert "uq_quota_active_tenant_total" in indexes

    reservation_constraints = {constraint.name for constraint in reservation_table.constraints}
    assert any(
        name.endswith("ck_quota_reservation_allocation_mode")
        for name in reservation_constraints
    )


def test_reserved_and_shared_applications_use_one_tenant_pool() -> None:
    tenant = SimpleNamespace(limit_bytes=1000, used_bytes=100, reserved_bytes=0)
    applications = [
        SimpleNamespace(limit_bytes=400, used_bytes=150, reserved_bytes=20),
        SimpleNamespace(limit_bytes=0, used_bytes=0, reserved_bytes=0),
    ]
    snapshot = build_snapshot(tenant, applications)

    assert snapshot.tenant_limit == 1000
    assert snapshot.allocated_application_limit == 400
    assert snapshot.shared_pool_limit == 600
    assert snapshot.shared_pool_used == 0
    assert snapshot.shared_pool_available == 600
