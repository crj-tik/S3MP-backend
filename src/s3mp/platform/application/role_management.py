"""Lifecycle operations for global platform-role bindings."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.platform.domain.context import PlatformContext


class PlatformRoleStore(Protocol):
    async def replace_platform_role_assignment(
        self,
        *,
        actor_user_id: UUID,
        user_id: UUID,
        role_names: Sequence[str],
        expires_at: datetime | None,
    ) -> dict[str, object]: ...

    async def grant_platform_role(
        self, *, actor_user_id: UUID, user_id: UUID, role_name: str, expires_at: datetime | None
    ) -> dict[str, object]: ...

    async def revoke_platform_role_assignment(
        self, *, actor_user_id: UUID, user_id: UUID
    ) -> bool: ...


class PlatformRoleManagementService:
    def __init__(self, store: PlatformRoleStore) -> None:
        self._store = store

    async def assign(
        self,
        actor: PlatformContext,
        *,
        user_id: UUID,
        role_names: Sequence[str],
        expires_at: datetime | None,
    ) -> dict[str, object]:
        if expires_at is not None and expires_at.tzinfo is None:
            raise ApiError(
                "validation_failed", "Role expiry must include a timezone", status_code=422
            )
        try:
            return await self._store.replace_platform_role_assignment(
                actor_user_id=actor.user_id,
                user_id=user_id,
                role_names=role_names,
                expires_at=expires_at,
            )
        except ValueError as exc:
            raise ApiError("conflict", str(exc), status_code=409) from exc

    async def revoke(self, actor: PlatformContext, user_id: UUID) -> None:
        if not await self._store.revoke_platform_role_assignment(
            actor_user_id=actor.user_id, user_id=user_id
        ):
            raise ApiError(
                "resource_not_found", "Platform role assignment not found", status_code=404
            )
