"""Deterministic quota reservation, settlement, and reconciliation."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ReservationStatus(StrEnum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"
    QUARANTINED = "quarantined"


class QuotaScope(StrEnum):
    TENANT = "tenant"
    APPLICATION = "application"
    STORAGE_SPACE = "storage_space"


class QuotaAllocationMode(StrEnum):
    TENANT_TOTAL = "tenant_total"
    APPLICATION_RESERVED = "application_reserved"
    STORAGE_SPACE_LEGACY = "storage_space_legacy"


class QuotaLifecycleStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    LEGACY = "legacy"


class QuotaExceededError(ValueError):
    code = "quota_exceeded"


@dataclass(frozen=True, slots=True)
class Quota:
    id: UUID
    tenant_id: UUID
    storage_space_id: UUID | None
    limit_bytes: int
    used_bytes: int = 0
    reserved_bytes: int = 0


@dataclass(frozen=True, slots=True)
class QuotaReservation:
    id: UUID
    quota_id: UUID
    tenant_id: UUID
    requested_bytes: int
    status: ReservationStatus = ReservationStatus.RESERVED
    actual_bytes: int | None = None
    created_at: datetime = datetime.now(UTC)


class QuotaService:
    def reserve(self, quota: Quota, bytes_requested: int) -> tuple[Quota, QuotaReservation]:
        if (
            bytes_requested < 0
            or quota.used_bytes + quota.reserved_bytes + bytes_requested > quota.limit_bytes
        ):
            raise QuotaExceededError("quota capacity exceeded")
        reservation = QuotaReservation(uuid4(), quota.id, quota.tenant_id, bytes_requested)
        return replace(quota, reserved_bytes=quota.reserved_bytes + bytes_requested), reservation

    def settle(
        self, quota: Quota, reservation: QuotaReservation, actual_bytes: int
    ) -> tuple[Quota, QuotaReservation]:
        self._active(quota, reservation)
        if actual_bytes < 0 or quota.used_bytes + actual_bytes > quota.limit_bytes:
            raise QuotaExceededError("actual object exceeds quota")
        updated = replace(
            quota,
            reserved_bytes=quota.reserved_bytes - reservation.requested_bytes,
            used_bytes=quota.used_bytes + actual_bytes,
        )
        return updated, replace(
            reservation, status=ReservationStatus.SETTLED, actual_bytes=actual_bytes
        )

    def release(
        self, quota: Quota, reservation: QuotaReservation
    ) -> tuple[Quota, QuotaReservation]:
        self._active(quota, reservation)
        return (
            replace(quota, reserved_bytes=quota.reserved_bytes - reservation.requested_bytes),
            replace(reservation, status=ReservationStatus.RELEASED),
        )

    def reconcile(self, quota: Quota, actual_used_bytes: int) -> Quota:
        if actual_used_bytes < 0:
            raise ValueError("actual usage must not be negative")
        return replace(quota, used_bytes=actual_used_bytes)

    @staticmethod
    def _active(quota: Quota, reservation: QuotaReservation) -> None:
        if reservation.quota_id != quota.id or reservation.status is not ReservationStatus.RESERVED:
            raise ValueError("reservation is not active for this quota")
