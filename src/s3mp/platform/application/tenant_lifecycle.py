"""Platform-governed tenant lifecycle without a data-plane authorization bypass."""

from typing import Protocol
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.platform.domain.context import PlatformContext


class PlatformTenantStore(Protocol):
    async def list_platform_tenants(self) -> list[dict[str, object]]: ...

    async def get_platform_tenant(self, tenant_id: UUID) -> dict[str, object] | None: ...

    async def create_platform_tenant(
        self, *, slug: str, name: str, initial_admin_user_id: UUID, actor_user_id: UUID
    ) -> dict[str, object]: ...

    async def update_platform_tenant(
        self, *, tenant_id: UUID, name: str | None, status: str | None, actor_user_id: UUID
    ) -> dict[str, object] | None: ...


class PlatformTenantLifecycleService:
    def __init__(self, store: PlatformTenantStore) -> None:
        self._store = store

    async def list_tenants(self, _actor: PlatformContext) -> list[dict[str, object]]:
        return await self._store.list_platform_tenants()

    async def get_tenant(self, _actor: PlatformContext, tenant_id: UUID) -> dict[str, object]:
        tenant = await self._store.get_platform_tenant(tenant_id)
        if tenant is None:
            raise ApiError("resource_not_found", "Tenant not found", status_code=404)
        return tenant

    async def create_tenant(
        self, actor: PlatformContext, *, slug: str, name: str, initial_admin_user_id: UUID
    ) -> dict[str, object]:
        try:
            return await self._store.create_platform_tenant(
                slug=slug,
                name=name,
                initial_admin_user_id=initial_admin_user_id,
                actor_user_id=actor.user_id,
            )
        except ValueError as exc:
            raise ApiError("conflict", str(exc), status_code=409) from exc

    async def update_tenant(
        self, actor: PlatformContext, tenant_id: UUID, *, name: str | None, status: str | None
    ) -> dict[str, object]:
        if name is None and status is None:
            raise ApiError("validation_failed", "At least one update is required", status_code=422)
        if status not in {None, "active", "suspended"}:
            raise ApiError("validation_failed", "Invalid tenant status", status_code=422)
        tenant = await self._store.update_platform_tenant(
            tenant_id=tenant_id, name=name, status=status, actor_user_id=actor.user_id
        )
        if tenant is None:
            raise ApiError("resource_not_found", "Tenant not found", status_code=404)
        return tenant
