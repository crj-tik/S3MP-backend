"""Public GiB conversion behavior for quota configuration and presentation."""

from decimal import Decimal

import pytest

from s3mp.governance.domain.units import GIB_BYTES, bytes_to_gib, gib_to_bytes


def test_gib_to_bytes_is_exact() -> None:
    assert gib_to_bytes(3) == 3 * GIB_BYTES


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_gib_to_bytes_rejects_non_integer_or_negative_values(value: object) -> None:
    with pytest.raises(ValueError):
        gib_to_bytes(value)  # type: ignore[arg-type]


def test_bytes_to_gib_preserves_fractional_usage() -> None:
    assert bytes_to_gib(GIB_BYTES + GIB_BYTES // 2) == Decimal("1.5")
