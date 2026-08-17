"""Read-only platform control-plane queries and safe summaries."""

from typing import Protocol
from uuid import UUID

from s3mp.platform.domain.context import PlatformContext


class PlatformControlPlaneStore(Protocol):
    async def list_platform_accounts(
        self, *, limit: int, cursor: UUID | None, query: str | None, status: str | None
    ) -> tuple[list[dict[str, object]], UUID | None]: ...

    async def get_platform_account(self, user_id: UUID) -> dict[str, object] | None: ...

    async def list_platform_roles(
        self, *, limit: int, cursor: UUID | None
    ) -> tuple[list[dict[str, object]], UUID | None]: ...

    async def list_platform_role_bindings(
        self, *, limit: int, cursor: UUID | None
    ) -> tuple[list[dict[str, object]], UUID | None]: ...

    async def list_support_access(
        self, *, limit: int, cursor: UUID | None, status: str | None
    ) -> tuple[list[dict[str, object]], UUID | None]: ...

    async def get_support_access(self, request_id: UUID) -> dict[str, object] | None: ...

    async def list_platform_audit_events(
        self, *, limit: int, cursor: UUID | None, action: str | None
    ) -> tuple[list[dict[str, object]], UUID | None]: ...

    async def get_platform_audit_event(self, event_id: UUID) -> dict[str, object] | None: ...


class PlatformControlPlaneService:
    def __init__(self, store: PlatformControlPlaneStore) -> None:
        self._store = store

    async def list_accounts(
        self,
        _actor: PlatformContext,
        *,
        limit: int,
        cursor: UUID | None,
        query: str | None,
        status: str | None,
    ) -> tuple[list[dict[str, object]], UUID | None]:
        return await self._store.list_platform_accounts(
            limit=limit, cursor=cursor, query=query, status=status
        )

    async def get_account(
        self, _actor: PlatformContext, user_id: UUID
    ) -> dict[str, object] | None:
        return await self._store.get_platform_account(user_id)

    async def list_roles(
        self, _actor: PlatformContext, *, limit: int, cursor: UUID | None
    ) -> tuple[list[dict[str, object]], UUID | None]:
        return await self._store.list_platform_roles(limit=limit, cursor=cursor)

    async def list_role_bindings(
        self, _actor: PlatformContext, *, limit: int, cursor: UUID | None
    ) -> tuple[list[dict[str, object]], UUID | None]:
        return await self._store.list_platform_role_bindings(limit=limit, cursor=cursor)

    async def list_support(
        self, _actor: PlatformContext, *, limit: int, cursor: UUID | None, status: str | None
    ) -> tuple[list[dict[str, object]], UUID | None]:
        return await self._store.list_support_access(limit=limit, cursor=cursor, status=status)

    async def get_support(
        self, _actor: PlatformContext, request_id: UUID
    ) -> dict[str, object] | None:
        return await self._store.get_support_access(request_id)

    async def list_audit(
        self, _actor: PlatformContext, *, limit: int, cursor: UUID | None, action: str | None
    ) -> tuple[list[dict[str, object]], UUID | None]:
        return await self._store.list_platform_audit_events(
            limit=limit, cursor=cursor, action=action
        )

    async def get_audit(
        self, _actor: PlatformContext, event_id: UUID
    ) -> dict[str, object] | None:
        return await self._store.get_platform_audit_event(event_id)
