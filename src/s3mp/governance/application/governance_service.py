"""Quota and audit application services."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.governance.domain.quota import QuotaAllocationMode, QuotaScope
from s3mp.governance.domain.units import gib_to_bytes
from s3mp.identity.domain.context import PrincipalContext
from s3mp.platform.domain.context import PlatformContext


class QuotaStore(Protocol):
    async def list_quotas(
        self,
        tenant_id: UUID,
        storage_space_id: str | None,
        limit: int,
        cursor: str | None,
        application_id: str | None = None,
        scope: QuotaScope | None = None,
        status: str | None = "active",
        allocation_mode: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]: ...
    async def get_quota(self, tenant_id: UUID, quota_id: UUID) -> dict[str, Any] | None: ...
    async def update_quota(
        self, tenant_id: UUID, quota_id: UUID, limit_bytes: int
    ) -> dict[str, Any] | None: ...


class AuditStore(Protocol):
    async def list_events(
        self, tenant_id: UUID, filters: dict[str, Any], limit: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]: ...
    async def get_event(self, tenant_id: UUID, event_id: UUID) -> dict[str, Any] | None: ...


class PermissionAuthorizer(Protocol):
    async def require_permission(self, context: PrincipalContext, permission: str) -> None: ...


@dataclass
class QuotaService:
    store: QuotaStore
    authorizer: PermissionAuthorizer | None = None

    async def list_quotas(
        self,
        context: PrincipalContext,
        storage_space_id: str | None,
        limit: int = 50,
        cursor: str | None = None,
        application_id: str | None = None,
        scope: QuotaScope | None = None,
        status: str | None = "active",
        allocation_mode: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        await self._require(context, "quotas.read")
        return await self.store.list_quotas(
            context.tenant_id,
            storage_space_id,
            min(limit, 200),
            cursor,
            application_id=application_id,
            scope=scope,
            status=status,
            allocation_mode=allocation_mode,
        )

    async def get_quota(self, context: PrincipalContext, quota_id: str) -> dict[str, Any]:
        await self._require(context, "quotas.read")
        result = await self.store.get_quota(context.tenant_id, UUID(quota_id))
        if result is None:
            raise ApiError("resource_not_found", "Quota not found", status_code=404)
        return result

    async def update_quota(
        self, context: PrincipalContext, quota_id: str, limit_gib: int
    ) -> dict[str, Any]:
        await self._require(context, "quotas.manage")
        try:
            limit_bytes = gib_to_bytes(limit_gib)
        except ValueError as exc:
            raise ApiError("validation_failed", str(exc), status_code=422) from exc
        result = await self.store.update_quota(context.tenant_id, UUID(quota_id), limit_bytes)
        if result is None:
            raise ApiError("resource_not_found", "Quota not found", status_code=404)
        return result

    async def _require(self, context: PrincipalContext, permission: str) -> None:
        if self.authorizer is None:
            raise ApiError(
                "internal_error", "Authorization management is not configured", status_code=500
            )
        await self.authorizer.require_permission(context, permission)


class PlatformQuotaStore(Protocol):
    async def list_platform_quotas(
        self,
        *,
        tenant_id: UUID | None,
        application_id: UUID | None,
        status: str | None,
        allocation_mode: QuotaAllocationMode | None,
        limit: int,
        cursor: UUID | None,
    ) -> tuple[list[dict[str, Any]], UUID | None]: ...

    async def create_platform_quota(
        self,
        *,
        actor_user_id: UUID,
        tenant_id: UUID,
        application_id: UUID | None,
        limit_bytes: int,
        bucket_capacity_bytes: int | None,
    ) -> dict[str, Any]: ...

    async def update_platform_quota(
        self,
        actor_user_id: UUID,
        quota_id: UUID,
        limit_bytes: int,
        bucket_capacity_bytes: int | None,
    ) -> dict[str, Any] | None: ...

    async def revoke_platform_quota(
        self, *, actor_user_id: UUID, quota_id: UUID
    ) -> dict[str, Any] | None: ...


@dataclass
class PlatformQuotaService:
    store: PlatformQuotaStore
    bucket_capacity_bytes: int | None = None

    async def list_quotas(
        self,
        _context: PlatformContext,
        *,
        tenant_id: UUID | None,
        application_id: UUID | None,
        status: str | None,
        allocation_mode: QuotaAllocationMode | None,
        limit: int,
        cursor: UUID | None,
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        return await self.store.list_platform_quotas(
            tenant_id=tenant_id,
            application_id=application_id,
            status=status,
            allocation_mode=allocation_mode,
            limit=min(limit, 200),
            cursor=cursor,
        )

    async def create_quota(
        self,
        context: PlatformContext,
        *,
        tenant_id: UUID,
        application_id: UUID | None,
        limit_gib: int,
    ) -> dict[str, Any]:
        try:
            limit_bytes = gib_to_bytes(limit_gib)
        except ValueError as exc:
            raise ApiError("validation_failed", str(exc), status_code=422) from exc
        return await self.store.create_platform_quota(
            actor_user_id=context.user_id,
            tenant_id=tenant_id,
            application_id=application_id,
            limit_bytes=limit_bytes,
            bucket_capacity_bytes=self.bucket_capacity_bytes,
        )

    async def update_quota(
        self, context: PlatformContext, quota_id: UUID, limit_gib: int
    ) -> dict[str, Any]:
        try:
            limit_bytes = gib_to_bytes(limit_gib)
        except ValueError as exc:
            raise ApiError("validation_failed", str(exc), status_code=422) from exc
        result = await self.store.update_platform_quota(
            context.user_id, quota_id, limit_bytes, self.bucket_capacity_bytes
        )
        if result is None:
            raise ApiError("resource_not_found", "Platform quota not found", 404)
        return result

    async def revoke_quota(self, context: PlatformContext, quota_id: UUID) -> dict[str, Any]:
        result = await self.store.revoke_platform_quota(
            actor_user_id=context.user_id, quota_id=quota_id
        )
        if result is None:
            raise ApiError("resource_not_found", "Platform quota not found", 404)
        return result


@dataclass
class AuditService:
    store: AuditStore
    authorizer: PermissionAuthorizer | None = None

    async def list_audit_events(
        self, context: PrincipalContext, limit: int = 50, cursor: str | None = None, **filters: Any
    ) -> tuple[list[dict[str, Any]], str | None]:
        await self._require(context, "audit.read")
        return await self.store.list_events(
            context.tenant_id,
            {key: value for key, value in filters.items() if value is not None},
            min(limit, 200),
            cursor,
        )

    async def get_audit_event(self, context: PrincipalContext, event_id: str) -> dict[str, Any]:
        await self._require(context, "audit.read")
        result = await self.store.get_event(context.tenant_id, UUID(event_id))
        if result is None:
            raise ApiError("resource_not_found", "Audit event not found", status_code=404)
        return result

    async def _require(self, context: PrincipalContext, permission: str) -> None:
        if self.authorizer is None:
            raise ApiError(
                "internal_error", "Authorization management is not configured", status_code=500
            )
        await self.authorizer.require_permission(context, permission)
