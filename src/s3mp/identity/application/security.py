"""Security primitives used by local password authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class PasswordHasher:
    """Memory-hard password hashing using the Python standard library scrypt."""

    algorithm = "scrypt"

    def __init__(self, *, n: int = 2**14, r: int = 8, p: int = 1) -> None:
        self.n = n
        self.r = r
        self.p = p

    def hash(self, password: str) -> str:
        if not password:
            raise ValueError("password must not be empty")
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=self.n, r=self.r, p=self.p, dklen=32
        )
        return f"{self.algorithm}${self.n}${self.r}${self.p}${_b64(salt)}${_b64(digest)}"

    def verify(self, password: str, encoded: str) -> bool:
        try:
            algorithm, n, r, p, salt, expected = encoded.split("$", 5)
            if algorithm != self.algorithm:
                return False
            digest = hashlib.scrypt(
                password.encode("utf-8"),
                salt=_unb64(salt),
                n=int(n),
                r=int(r),
                p=int(p),
                dklen=32,
            )
            return hmac.compare_digest(digest, _unb64(expected))
        except (TypeError, ValueError, OverflowError):
            return False


@dataclass(frozen=True, slots=True)
class SessionTokens:
    """Opaque values returned only to the browser; persistence stores digests."""

    session_token: str
    csrf_token: str


class SessionTokenService:
    """Issue and verify opaque session and CSRF tokens without storing plaintext."""

    def __init__(self, pepper: bytes) -> None:
        if len(pepper) < 32:
            raise ValueError("session pepper must be at least 32 bytes")
        self._pepper = pepper

    def issue(self) -> SessionTokens:
        return SessionTokens(_b64(secrets.token_bytes(32)), _b64(secrets.token_bytes(32)))

    def digest(self, token: str) -> bytes:
        return hmac.new(self._pepper, token.encode("ascii"), hashlib.sha256).digest()

    def verify(self, token: str, expected_digest: bytes) -> bool:
        try:
            actual = self.digest(token)
        except (UnicodeEncodeError, ValueError):
            return False
        return hmac.compare_digest(actual, expected_digest)

    def verify_csrf(self, cookie_token: str, header_token: str) -> bool:
        if not cookie_token or not header_token:
            return False
        return hmac.compare_digest(cookie_token, header_token)


@dataclass(frozen=True, slots=True)
class SessionCookiePolicy:
    name: str = "s3mp_session"
    httponly: bool = True
    secure: bool = True
    samesite: str = "lax"
    path: str = "/"


class LoginRateLimiter(Protocol):
    async def allow(self, key: str, *, now: float | None = None) -> bool: ...


@dataclass(frozen=True, slots=True)
class PasswordCredential:
    user_id: UUID
    password_hash: str | None


class PasswordCredentialStore(Protocol):
    async def find_by_normalized_email(
        self, normalized_email: str
    ) -> PasswordCredential | None: ...


class AuthenticationFailed(Exception):
    """Safe authentication failure that does not disclose which check failed."""


class LoginRateLimited(Exception):
    """The login attempt key is over its configured budget."""


class LocalPasswordAuthenticator:
    """Authenticate local credentials without exposing account existence."""

    def __init__(self, store: PasswordCredentialStore, limiter: LoginRateLimiter) -> None:
        self._store = store
        self._limiter = limiter
        self._hasher = PasswordHasher()

    async def authenticate(self, email: str, password: str, *, rate_limit_key: str) -> UUID:
        if not await self._limiter.allow(rate_limit_key):
            raise LoginRateLimited
        normalized_email = email.strip().casefold()
        credential = await self._store.find_by_normalized_email(normalized_email)
        if credential is None or credential.password_hash is None:
            raise AuthenticationFailed
        if not self._hasher.verify(password, credential.password_hash):
            raise AuthenticationFailed
        return credential.user_id


class InMemoryLoginRateLimiter:
    """Small process-local fallback; production deployments should use Redis."""

    def __init__(self, *, limit: int = 5, window_seconds: int = 300) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("rate limit and window must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: MutableMapping[str, deque[float]] = defaultdict(deque)

    async def allow(self, key: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        attempts = self._attempts[key]
        cutoff = current - self.window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= self.limit:
            return False
        attempts.append(current)
        return True
