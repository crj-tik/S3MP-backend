"""Canonical SHA-256 handling for knowledge-source provenance."""

import re

_SHA256 = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


class InvalidSourceChecksum(ValueError):
    """A declared source checksum is not a SHA-256 value."""


class SourceChecksumMismatch(ValueError):
    """Fetched source bytes do not match the declared canonical SHA-256."""


def normalize_declared_sha256(value: str | None) -> str | None:
    """Return the canonical digest, retaining ``None`` for legacy uploads."""
    if value is None:
        return None
    match = _SHA256.fullmatch(value.strip())
    if match is None:
        raise InvalidSourceChecksum("checksum must be sha256:<64 lowercase hex characters>")
    return match.group(1).lower()
