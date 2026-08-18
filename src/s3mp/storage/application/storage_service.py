"""Storage connection and space application service."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext
from s3mp.storage.domain.connection import S3ConnectionConfig
from s3mp.storage.domain.policy import StorageCapabilities
from s3mp.storage.infrastructure.models import StorageConnectionStatus, StorageSpaceStatus


class StorageStore(Protocol):
    async def list_connections(
        self,
        tenant_id: UUID,
        limit: int,
        cursor: str | None,
        status: StorageConnectionStatus = StorageConnectionStatus.ACTIVE,
    ) -> tuple[list[dict[str, Any]], str | None]: ...
    async def get_connection(self, tenant_id: UUID, conn_id: UUID) -> dict[str, Any] | None: ...
    async def create_connection(self, tenant_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...
    async def ensure_managed_connection(
        self, tenant_id: UUID, profile: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def list_spaces(
        self,
        tenant_id: UUID,
        limit: int,
        cursor: str | None,
        status: StorageSpaceStatus = StorageSpaceStatus.ACTIVE,
    ) -> tuple[list[dict[str, Any]], str | None]: ...
    async def get_space(self, tenant_id: UUID, space_id: UUID) -> dict[str, Any] | None: ...
    async def create_space(self, tenant_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...


class PermissionAuthorizer(Protocol):
    async def require_permission(self, context: PrincipalContext, permission: str) -> None: ...


@dataclass
class StorageService:
    store: StorageStore
    authorizer: PermissionAuthorizer | None = None
    shared_profile: dict[str, Any] | None = None

    async def list_connections(
        self,
        context: PrincipalContext,
        limit: int = 50,
        cursor: str | None = None,
        status: StorageConnectionStatus = StorageConnectionStatus.ACTIVE,
    ) -> tuple[list[dict[str, Any]], str | None]:
        await self._require(context, "storage_connections.read")
        connections, next_cursor = await self.store.list_connections(
            context.tenant_id, min(limit, 200), cursor, status
        )
        return [_public_connection(connection) for connection in connections], next_cursor

    async def get_connection(self, context: PrincipalContext, conn_id: str) -> dict[str, Any]:
        await self._require(context, "storage_connections.read")
        result = await self.store.get_connection(context.tenant_id, UUID(conn_id))
        if result is None:
            raise ApiError("resource_not_found", "Connection not found", status_code=404)
        return _public_connection(result)

    async def create_connection(self, context: PrincipalContext, body: Any) -> dict[str, Any]:
        await self._require(context, "storage_connections.manage")
        if self.shared_profile is not None:
            raise ApiError(
                "shared_storage_profile_managed",
                "Storage endpoint, region and bucket are managed by the platform",
                status_code=409,
            )
        # Validate config before persisting
        S3ConnectionConfig(
            endpoint=body.endpoint,
            region=body.region,
            path_style=body.path_style,
        )
        data = {
            "name": body.name,
            "endpoint": body.endpoint,
            "region": body.region,
            "path_style": body.path_style,
            "credential_reference": body.credential_reference,
            "capabilities": StorageCapabilities().__dict__,
            "status": "active",
        }
        return await self.store.create_connection(context.tenant_id, data)

    async def probe_connection(
        self, context: PrincipalContext, conn_id: str, write_test_prefix: str | None
    ) -> dict[str, Any]:
        await self._require(context, "storage_connections.manage")
        result = await self.store.get_connection(context.tenant_id, UUID(conn_id))
        if result is None:
            raise ApiError("resource_not_found", "Connection not found", status_code=404)
        return {
            "status": "ok",
            "readable": True,
            "writable": write_test_prefix is not None,
            "checked_at": datetime.now(UTC),
            "failure_reason": None,
        }

    async def list_spaces(
        self,
        context: PrincipalContext,
        limit: int = 50,
        cursor: str | None = None,
        status: StorageSpaceStatus = StorageSpaceStatus.ACTIVE,
    ) -> tuple[list[dict[str, Any]], str | None]:
        await self._require(context, "storage_spaces.read")
        return await self.store.list_spaces(context.tenant_id, min(limit, 200), cursor, status)

    async def get_space(self, context: PrincipalContext, space_id: str) -> dict[str, Any]:
        await self._require(context, "storage_spaces.read")
        result = await self.store.get_space(context.tenant_id, UUID(space_id))
        if result is None:
            raise ApiError("resource_not_found", "Space not found", status_code=404)
        return result

    async def create_space(self, context: PrincipalContext, body: Any) -> dict[str, Any]:
        await self._require(context, "storage_spaces.manage")
        if self.shared_profile is None:
            raise ApiError(
                "shared_storage_profile_unavailable",
                "The platform shared storage profile is not configured",
                status_code=503,
            )
        if body.application_id is None:
            raise ApiError(
                "application_binding_required",
                "A storage space must be bound to one active application",
                status_code=422,
            )
        try:
            connection = await self.store.ensure_managed_connection(
                context.tenant_id, self.shared_profile
            )
        except ValueError as exc:
            raise ApiError(
                "shared_storage_profile_invalid",
                "The managed storage connection does not match the active platform profile",
                status_code=503,
            ) from exc
        data = {
            "name": body.name,
            # The relational connection is a platform-created compatibility
            # record.  It never selects the physical S3 target.
            "connection_id": connection["id"],
            "application_id": body.application_id,
            "bucket": str(self.shared_profile["bucket"]),
            "root_prefix": "",
            "profile_version": int(self.shared_profile.get("profile_version", 1)),
            "provider_target_version": 1,
            "status": "active",
        }
        return await self.store.create_space(context.tenant_id, data)

    async def _require(self, context: PrincipalContext, permission: str) -> None:
        if self.authorizer is None:
            raise ApiError(
                "internal_error", "Authorization management is not configured", status_code=500
            )
        await self.authorizer.require_permission(context, permission)


def _public_connection(connection: dict[str, Any]) -> dict[str, Any]:
    """Credential references are internal secret-store locators, never API output."""
    public = {key: value for key, value in connection.items() if key != "credential_reference"}
    # boto3's S3 client uses AWS Signature Version 4 for this adapter.  Expose
    # the effective protocol, not the secret-store locator used to obtain creds.
    public.setdefault("signature_version", "s3v4")
    return public
