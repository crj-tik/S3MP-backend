"""Conversions between the public GiB unit and the internal byte ledger."""

from decimal import Decimal

GIB_BYTES = 1024**3


def gib_to_bytes(value: int) -> int:
    """Convert a public integer GiB value without floating-point rounding."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("GiB value must be a non-negative integer")
    return value * GIB_BYTES


def bytes_to_gib(value: int | None) -> Decimal | None:
    """Render exact internal bytes as a Decimal GiB value for API responses."""
    if value is None:
        return None
    if value < 0:
        value = 0
    return Decimal(value) / Decimal(GIB_BYTES)
