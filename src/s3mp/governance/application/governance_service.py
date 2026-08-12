"""Quota and audit application services."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from s3mp.common.errors import ApiError


class QuotaStore(Protocol):
    async def list_quotas(self, tenant_id: UUID, storage_space_id: str | None) -> list[dict[str, Any]]: ...
    async def get_quota(self, tenant_id: UUID, quota_id: UUID) -> dict[str, Any] | None: ...
    async def update_quota(self, tenant_id: UUID, quota_id: UUID, limit_bytes: int) -> dict[str, Any] | None: ...


class AuditStore(Protocol):
    async def list_events(
        self, tenant_id: UUID, filters: dict[str, Any]
    ) -> list[dict[str, Any]]: ...
    async def get_event(self, tenant_id: UUID, event_id: UUID) -> dict[str, Any] | None: ...


@dataclass
class QuotaService:
    store: QuotaStore

    async def list_quotas(
        self, tenant_id: UUID, storage_space_id: str | None
    ) -> list[dict[str, Any]]:
        return await self.store.list_quotas(tenant_id, storage_space_id)

    async def get_quota(self, tenant_id: UUID, quota_id: str) -> dict[str, Any]:
        result = await self.store.get_quota(tenant_id, UUID(quota_id))
        if result is None:
            raise ApiError("resource_not_found", "Quota not found", status_code=404)
        return result

    async def update_quota(
        self, tenant_id: UUID, quota_id: str, limit_bytes: int
    ) -> dict[str, Any]:
        result = await self.store.update_quota(tenant_id, UUID(quota_id), limit_bytes)
        if result is None:
            raise ApiError("resource_not_found", "Quota not found", status_code=404)
        return result


@dataclass
class AuditService:
    store: AuditStore

    async def list_audit_events(
        self, tenant_id: UUID, **filters: Any
    ) -> list[dict[str, Any]]:
        return await self.store.list_events(tenant_id, {k: v for k, v in filters.items() if v is not None})

    async def get_audit_event(self, tenant_id: UUID, event_id: str) -> dict[str, Any]:
        result = await self.store.get_event(tenant_id, UUID(event_id))
        if result is None:
            raise ApiError("resource_not_found", "Audit event not found", status_code=404)
        return result