"""Security-audit output is deliberately aggregate and secret-free."""

from scripts.security_audit import _fingerprint


def test_conflict_fingerprint_is_stable_and_does_not_expose_source_values() -> None:
    value = _fingerprint("s3mp-dev", "customer-a/private")

    assert len(value) == 16
    assert "s3mp" not in value
    assert "customer" not in value
