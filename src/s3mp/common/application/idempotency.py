"""Durable idempotency-key fingerprint and replay handling."""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from s3mp.common.errors import ApiError


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    key: str
    tenant_id: UUID
    principal_id: UUID
    method: str
    route: str
    response_hash: str
    created_at: datetime


class IdempotencyGuard:
    """Stateless guard that fingerprints requests and detects replays.

    Production deployments should use a Redis-backed store; the
    fingerprint logic is shared regardless of storage backend.
    """

    def __init__(self, secret: bytes) -> None:
        if len(secret) < 16:
            raise ValueError("idempotency secret must be at least 16 bytes")
        self._secret = secret

    def fingerprint(
        self,
        key: str,
        tenant_id: UUID,
        principal_id: UUID,
        method: str,
        route: str,
        body_hash: str,
    ) -> str:
        """Produce a stable, opaque fingerprint bound to the exact request scope."""
        payload = "|".join(
            [
                key,
                str(tenant_id),
                str(principal_id),
                method.upper(),
                route,
                body_hash,
            ]
        )
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def validate_key(value: str | None) -> str:
        """Validate the Idempotency-Key header value."""
        if not value or not (8 <= len(value) <= 128):
            raise ApiError(
                "invalid_idempotency_key",
                "Idempotency-Key must be 8-128 characters",
                status_code=400,
            )
        return value

    @staticmethod
    def key_reused() -> ApiError:
        return ApiError(
            "idempotency_key_reused",
            "A different request was already submitted with this key",
            status_code=409,
        )