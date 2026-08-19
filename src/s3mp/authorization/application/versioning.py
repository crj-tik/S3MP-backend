"""Authorization-version invalidation primitives for sessions and queued work."""

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class StaleAuthorization(Exception):
    """A value was created under an older authorization version."""


class AuthorizationVersionStore(Protocol):
    async def current(self, tenant_id: UUID) -> int: ...

    async def bump(self, tenant_id: UUID) -> int: ...


class InMemoryAuthorizationVersionStore:
    def __init__(self) -> None:
        self._versions: MutableMapping[UUID, int] = {}

    async def current(self, tenant_id: UUID) -> int:
        return self._versions.get(tenant_id, 1)

    async def bump(self, tenant_id: UUID) -> int:
        version = await self.current(tenant_id) + 1
        self._versions[tenant_id] = version
        return version


@dataclass(frozen=True, slots=True)
class VersionedValue:
    value: object
    authorization_version: int


class VersionedAuthorizationCache:
    """Cache that never returns a value from an older authorization version."""

    def __init__(self) -> None:
        self._values: MutableMapping[str, VersionedValue] = {}

    def put(self, key: str, value: object, authorization_version: int) -> None:
        self._values[key] = VersionedValue(value, authorization_version)

    def get(self, key: str, authorization_version: int) -> object | None:
        cached = self._values.get(key)
        if cached is None or cached.authorization_version != authorization_version:
            return None
        return cached.value

    def invalidate(self, key: str) -> None:
        self._values.pop(key, None)


def application_authorization_cache_key(
    tenant_id: UUID,
    application_id: UUID,
    membership_id: UUID | None,
    *,
    application_version: int,
    membership_version: int = 0,
    key_id: UUID | None = None,
    group_version: int = 0,
) -> str:
    """Build a tenant-safe cache key for delegated application decisions.

    Version components are deliberately part of the key as well as the
    VersionedAuthorizationCache value. Any representative replacement,
    membership change, group change, application lifecycle transition, or key
    rotation therefore misses stale entries without relying on best-effort
    invalidation messages.
    """
    return ":".join(
        (
            "authz",
            "application",
            str(tenant_id),
            str(application_id),
            str(membership_id or "none"),
            f"av{application_version}",
            f"mv{membership_version}",
            f"gv{group_version}",
            str(key_id or "none"),
        )
    )


def require_current_version(value_version: int, current_version: int) -> None:
    if value_version != current_version:
        raise StaleAuthorization
