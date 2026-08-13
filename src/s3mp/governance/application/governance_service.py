"""Quota and audit application services."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext


class QuotaStore(Protocol):
    async def list_quotas(self, tenant_id: UUID, storage_space_id: str | None) -> list[dict[str, Any]]: ...
    async def get_quota(self, tenant_id: UUID, quota_id: UUID) -> dict[str, Any] | None: ...
    async def update_quota(self, tenant_id: UUID, quota_id: UUID, limit_bytes: int) -> dict[str, Any] | None: ...


class AuditStore(Protocol):
    async def list_events(
        self, tenant_id: UUID, filters: dict[str, Any]
    ) -> list[dict[str, Any]]: ...
    async def get_event(self, tenant_id: UUID, event_id: UUID) -> dict[str, Any] | None: ...


class PermissionAuthorizer(Protocol):
    async def require_permission(self, context: PrincipalContext, permission: str) -> None: ...


@dataclass
class QuotaService:
    store: QuotaStore
    authorizer: PermissionAuthorizer | None = None

    async def list_quotas(
        self, context: PrincipalContext, storage_space_id: str | None
    ) -> list[dict[str, Any]]:
        await self._require(context, "quotas.read")
        return await self.store.list_quotas(context.tenant_id, storage_space_id)

    async def get_quota(self, context: PrincipalContext, quota_id: str) -> dict[str, Any]:
        await self._require(context, "quotas.read")
        result = await self.store.get_quota(context.tenant_id, UUID(quota_id))
        if result is None:
            raise ApiError("resource_not_found", "Quota not found", status_code=404)
        return result

    async def update_quota(
        self, context: PrincipalContext, quota_id: str, limit_bytes: int
    ) -> dict[str, Any]:
        await self._require(context, "quotas.manage")
        result = await self.store.update_quota(context.tenant_id, UUID(quota_id), limit_bytes)
        if result is None:
            raise ApiError("resource_not_found", "Quota not found", status_code=404)
        return result

    async def _require(self, context: PrincipalContext, permission: str) -> None:
        if self.authorizer is None:
            raise ApiError("internal_error", "Authorization management is not configured", status_code=500)
        await self.authorizer.require_permission(context, permission)


@dataclass
class AuditService:
    store: AuditStore
    authorizer: PermissionAuthorizer | None = None

    async def list_audit_events(
        self, context: PrincipalContext, **filters: Any
    ) -> list[dict[str, Any]]:
        await self._require(context, "audit.read")
        return await self.store.list_events(context.tenant_id, {k: v for k, v in filters.items() if v is not None})

    async def get_audit_event(self, context: PrincipalContext, event_id: str) -> dict[str, Any]:
        await self._require(context, "audit.read")
        result = await self.store.get_event(context.tenant_id, UUID(event_id))
        if result is None:
            raise ApiError("resource_not_found", "Audit event not found", status_code=404)
        return result

    async def _require(self, context: PrincipalContext, permission: str) -> None:
        if self.authorizer is None:
            raise ApiError("internal_error", "Authorization management is not configured", status_code=500)
        await self.authorizer.require_permission(context, permission)
