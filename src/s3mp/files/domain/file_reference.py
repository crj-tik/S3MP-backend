"""Stable public file-reference generation.

Provider ETags are intentionally excluded: they describe a provider write,
not a portable content identity.
"""

import base64
import hashlib
import json
import re
from uuid import UUID

PREFIX = "s3mpf1_"
_SHA256 = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


def normalized_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    match = _SHA256.fullmatch(value.strip())
    return match.group(1).lower() if match else None


def canonical_json(value: object | None) -> str:
    """Serialize JSON by value, retaining whitespace within JSON strings."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def generate_file_ref(
    *,
    tenant_id: UUID | str,
    application_id: UUID | str | None,
    relative_key: str,
    metadata: object | None,
    checksum: str | None,
) -> str | None:
    """Return a versioned opaque reference, or None for legacy/unverified input."""
    digest = normalized_sha256(checksum)
    if application_id is None or digest is None:
        return None
    fields = (
        "s3mp-file-ref:v1",
        str(tenant_id),
        str(application_id),
        relative_key,
        canonical_json(metadata),
        digest,
    )
    # Length-prefixing removes any ambiguity even where field values contain NUL.
    preimage = b"".join(
        len(item.encode("utf-8")).to_bytes(8, "big") + item.encode("utf-8") for item in fields
    )
    encoded = base64.urlsafe_b64encode(hashlib.sha256(preimage).digest()).rstrip(b"=").decode()
    return PREFIX + encoded


def is_file_ref(value: str) -> bool:
    return value.startswith(PREFIX)
