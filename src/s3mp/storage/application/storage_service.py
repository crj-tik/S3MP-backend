"""Storage connection and space application service."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext
from s3mp.storage.domain.connection import S3ConnectionConfig
from s3mp.storage.domain.policy import StorageCapabilities, canonical_operator_prefix


class StorageStore(Protocol):
    async def list_connections(self, tenant_id: UUID) -> list[dict[str, Any]]: ...
    async def get_connection(self, tenant_id: UUID, conn_id: UUID) -> dict[str, Any] | None: ...
    async def create_connection(self, tenant_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...
    async def list_spaces(self, tenant_id: UUID) -> list[dict[str, Any]]: ...
    async def get_space(self, tenant_id: UUID, space_id: UUID) -> dict[str, Any] | None: ...
    async def create_space(self, tenant_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...


class PermissionAuthorizer(Protocol):
    async def require_permission(self, context: PrincipalContext, permission: str) -> None: ...


@dataclass
class StorageService:
    store: StorageStore
    authorizer: PermissionAuthorizer | None = None

    async def list_connections(self, context: PrincipalContext) -> list[dict[str, Any]]:
        await self._require(context, "storage_connections.read")
        connections = await self.store.list_connections(context.tenant_id)
        return [_public_connection(connection) for connection in connections]

    async def get_connection(self, context: PrincipalContext, conn_id: str) -> dict[str, Any]:
        await self._require(context, "storage_connections.read")
        result = await self.store.get_connection(context.tenant_id, UUID(conn_id))
        if result is None:
            raise ApiError("resource_not_found", "Connection not found", status_code=404)
        return _public_connection(result)

    async def create_connection(self, context: PrincipalContext, body: Any) -> dict[str, Any]:
        await self._require(context, "storage_connections.manage")
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
        return {"status": "ok", "readable": True, "writable": write_test_prefix is not None}

    async def list_spaces(self, context: PrincipalContext) -> list[dict[str, Any]]:
        await self._require(context, "storage_spaces.read")
        return await self.store.list_spaces(context.tenant_id)

    async def get_space(self, context: PrincipalContext, space_id: str) -> dict[str, Any]:
        await self._require(context, "storage_spaces.read")
        result = await self.store.get_space(context.tenant_id, UUID(space_id))
        if result is None:
            raise ApiError("resource_not_found", "Space not found", status_code=404)
        return result

    async def create_space(self, context: PrincipalContext, body: Any) -> dict[str, Any]:
        await self._require(context, "storage_spaces.manage")
        try:
            root_prefix = canonical_operator_prefix(body.root_prefix)
        except ValueError as exc:
            raise ApiError(
                "validation_failed", "Storage root prefix is not canonical", status_code=422
            ) from exc
        data = {
            "name": body.name,
            "connection_id": body.connection_id,
            "bucket": body.bucket,
            "root_prefix": root_prefix,
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
    return {key: value for key, value in connection.items() if key != "credential_reference"}
