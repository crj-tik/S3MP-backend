"""Storage connection and space application service."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.storage.domain.connection import S3ConnectionConfig
from s3mp.storage.domain.policy import StorageCapabilities


class StorageStore(Protocol):
    async def list_connections(self, tenant_id: UUID) -> list[dict[str, Any]]: ...
    async def get_connection(self, tenant_id: UUID, conn_id: UUID) -> dict[str, Any] | None: ...
    async def create_connection(self, tenant_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...
    async def list_spaces(self, tenant_id: UUID) -> list[dict[str, Any]]: ...
    async def get_space(self, tenant_id: UUID, space_id: UUID) -> dict[str, Any] | None: ...
    async def create_space(self, tenant_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class StorageService:
    store: StorageStore

    async def list_connections(self, tenant_id: UUID) -> list[dict[str, Any]]:
        return await self.store.list_connections(tenant_id)

    async def get_connection(self, tenant_id: UUID, conn_id: str) -> dict[str, Any]:
        result = await self.store.get_connection(tenant_id, UUID(conn_id))
        if result is None:
            raise ApiError("resource_not_found", "Connection not found", status_code=404)
        # Redact credential reference
        result.pop("credential_reference", None)
        return result

    async def create_connection(self, tenant_id: UUID, body: Any) -> dict[str, Any]:
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
        return await self.store.create_connection(tenant_id, data)

    async def probe_connection(
        self, tenant_id: UUID, conn_id: str, write_test_prefix: str | None
    ) -> dict[str, Any]:
        result = await self.store.get_connection(tenant_id, UUID(conn_id))
        if result is None:
            raise ApiError("resource_not_found", "Connection not found", status_code=404)
        return {"status": "ok", "readable": True, "writable": write_test_prefix is not None}

    async def list_spaces(self, tenant_id: UUID) -> list[dict[str, Any]]:
        return await self.store.list_spaces(tenant_id)

    async def get_space(self, tenant_id: UUID, space_id: str) -> dict[str, Any]:
        result = await self.store.get_space(tenant_id, UUID(space_id))
        if result is None:
            raise ApiError("resource_not_found", "Space not found", status_code=404)
        return result

    async def create_space(self, tenant_id: UUID, body: Any) -> dict[str, Any]:
        data = {
            "name": body.name,
            "connection_id": body.connection_id,
            "bucket": body.bucket,
            "root_prefix": body.root_prefix,
            "status": "active",
        }
        return await self.store.create_space(tenant_id, data)