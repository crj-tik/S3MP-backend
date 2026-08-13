"""Two-person approved, expiring tenant support access."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.platform.domain.context import PlatformContext


class SupportAccessStore(Protocol):
    async def request_support_access(
        self, *, requester_user_id: UUID, tenant_id: UUID, reason: str, expires_at: datetime
    ) -> dict[str, object]: ...

    async def approve_support_access(
        self, *, approver_user_id: UUID, request_id: UUID
    ) -> dict[str, object] | None: ...

    async def revoke_support_access(
        self, *, actor_user_id: UUID | None, request_id: UUID
    ) -> bool: ...

    async def expire_support_access(self, *, now: datetime) -> int: ...


class SupportAccessService:
    def __init__(self, store: SupportAccessStore) -> None:
        self._store = store

    async def request(
        self, actor: PlatformContext, *, tenant_id: UUID, reason: str, expires_at: datetime
    ) -> dict[str, object]:
        if expires_at.tzinfo is None:
            raise ApiError("validation_failed", "Support expiry must include a timezone", 422)
        try:
            return await self._store.request_support_access(
                requester_user_id=actor.user_id,
                tenant_id=tenant_id,
                reason=reason,
                expires_at=expires_at,
            )
        except ValueError as exc:
            raise ApiError("conflict", str(exc), 409) from exc

    async def approve(self, actor: PlatformContext, request_id: UUID) -> dict[str, object]:
        try:
            result = await self._store.approve_support_access(
                approver_user_id=actor.user_id, request_id=request_id
            )
        except ValueError as exc:
            raise ApiError("conflict", str(exc), 409) from exc
        if result is None:
            raise ApiError("resource_not_found", "Support access request not found", 404)
        return result

    async def revoke(self, actor: PlatformContext, request_id: UUID) -> None:
        if not await self._store.revoke_support_access(
            actor_user_id=actor.user_id, request_id=request_id
        ):
            raise ApiError("resource_not_found", "Support access request not found", 404)
