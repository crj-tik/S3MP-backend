"""Conversions between S3 checksum wire values and S3MP canonical values."""

import base64
import binascii


def sha256_hex_to_base64(value: str) -> str:
    digest = bytes.fromhex(value.removeprefix("sha256:"))
    if len(digest) != 32:
        raise ValueError("SHA-256 digest must contain 32 bytes")
    return base64.b64encode(digest).decode("ascii")


def provider_checksum_to_hex(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    try:
        digest = bytes.fromhex(candidate.removeprefix("sha256:"))
        if len(digest) == 32:
            return digest.hex()
    except ValueError:
        pass
    try:
        digest = base64.b64decode(candidate, validate=True)
    except (ValueError, binascii.Error):
        return None
    return digest.hex() if len(digest) == 32 else None
