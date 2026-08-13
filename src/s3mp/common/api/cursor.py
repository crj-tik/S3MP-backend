"""Opaque cursor helpers bound to tenant, principal, authorization version, and query."""

import base64
import hashlib
import hmac
import json
from uuid import UUID

from s3mp.common.errors import ApiError


class CursorCodec:
    """Encode and verify opaque pagination cursors."""

    def __init__(self, secret: bytes) -> None:
        if len(secret) < 16:
            raise ValueError("cursor secret must be at least 16 bytes")
        self._secret = secret

    def encode(
        self,
        tenant_id: UUID,
        principal_id: UUID,
        authorization_version: int,
        position: str,
        *,
        query: str = "",
    ) -> str:
        payload = json.dumps(
            {
                "t": str(tenant_id),
                "p": str(principal_id),
                "v": authorization_version,
                "o": position,
                "q": query,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        sig = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + sig).decode().rstrip("=")

    def decode(
        self,
        token: str,
        tenant_id: UUID,
        principal_id: UUID,
        authorization_version: int,
        *,
        query: str = "",
    ) -> str:
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            payload, sig = raw[:-32], raw[-32:]
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(sig, expected):
                raise ValueError("cursor signature mismatch")
            data = json.loads(payload)
            if (
                data["t"] != str(tenant_id)
                or data["p"] != str(principal_id)
                or data["v"] != authorization_version
                or data.get("q") != query
            ):
                raise ValueError("cursor binding mismatch")
            return str(data["o"])
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise ApiError(
                "invalid_cursor",
                "The cursor is invalid, expired, or belongs to a different context",
                status_code=400,
            ) from exc
