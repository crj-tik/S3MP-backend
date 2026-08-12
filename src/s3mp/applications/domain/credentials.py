"""API-key issuance, verification and lifecycle rules."""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from s3mp.identity.application.security import InMemoryLoginRateLimiter


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class IssuedApiKey:
    key_id: str
    secret: str
    credential: str


class ApiKeyCredentialService:
    def __init__(self, pepper: bytes, *, pepper_version: int = 1) -> None:
        if len(pepper) < 32:
            raise ValueError("API key pepper must be at least 32 bytes")
        self._pepper = pepper
        self.pepper_version = pepper_version

    def issue(self) -> IssuedApiKey:
        key_id = "sk_" + _encode(secrets.token_bytes(16))
        secret = _encode(secrets.token_bytes(32))
        return IssuedApiKey(key_id, secret, f"{key_id}.{secret}")

    def digest(self, secret: str) -> bytes:
        return hmac.new(self._pepper, secret.encode("ascii"), hashlib.sha256).digest()

    def verify(self, secret: str, expected_digest: bytes) -> bool:
        try:
            return hmac.compare_digest(self.digest(secret), expected_digest)
        except (UnicodeEncodeError, ValueError):
            return False


def parse_credential(value: str) -> tuple[str, str]:
    if not value.startswith("S3MP-Key "):
        raise ValueError("invalid authorization scheme")
    credential = value.removeprefix("S3MP-Key ")
    key_id, separator, secret = credential.partition(".")
    if not separator or not key_id or not secret:
        raise ValueError("invalid API key credential")
    return key_id, secret


def key_is_usable(*, status: str, expires_at: datetime, now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    return status == "active" and expires_at > current


def require_scope_intersection(key_scopes: set[str], required_scopes: set[str]) -> None:
    if not required_scopes.issubset(key_scopes):
        raise PermissionError("API key scope is insufficient")


def effective_key_scopes(
    key_scopes: set[str],
    application_scopes: set[str],
    directory_scopes: set[str],
    governance_scopes: set[str],
    operation_allowlist: set[str],
) -> set[str]:
    """Return the intersection of every policy layer, never a union."""
    return (
        key_scopes
        & application_scopes
        & directory_scopes
        & governance_scopes
        & operation_allowlist
    )


def revoke_key(*, revoked_at: datetime, issued_until: datetime | None) -> datetime | None:
    """Revoke new use while preserving the audit-visible presigned exposure window."""
    return issued_until if issued_until is not None and issued_until > revoked_at else None


def orphaned_application(owner_ids: set[UUID], active_principal_ids: set[UUID]) -> bool:
    return not owner_ids.intersection(active_principal_ids)


class ApiKeyRateLimiter:
    """Apply independent key, application and tenant budgets."""

    def __init__(self, *, limit: int = 60, window_seconds: int = 60) -> None:
        self._key = InMemoryLoginRateLimiter(limit=limit, window_seconds=window_seconds)
        self._application = InMemoryLoginRateLimiter(limit=limit, window_seconds=window_seconds)
        self._tenant = InMemoryLoginRateLimiter(limit=limit, window_seconds=window_seconds)

    async def allow(self, *, key_id: str, application_id: UUID, tenant_id: UUID) -> bool:
        return all(
            (
                await self._key.allow(key_id),
                await self._application.allow(str(application_id)),
                await self._tenant.allow(str(tenant_id)),
            )
        )


def takeover_required(owner_ids: set[UUID], active_principal_ids: set[UUID]) -> bool:
    return orphaned_application(owner_ids, active_principal_ids)
