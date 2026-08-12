"""Upload, multipart, and object-operation command services with durable intent."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.files.infrastructure.repositories import SqlAlchemyFileStore


@dataclass
class UploadCommandService:
    store: SqlAlchemyFileStore

    async def create_upload(
        self, tenant_id: UUID, principal_id: UUID, space_id: UUID,
        object_key: str, content_length: int, content_type: str,
        *, checksum: str | None = None, direct_requested: bool = False,
    ) -> dict[str, Any]:
        data = {
            "principal_id": str(principal_id),
            "object_key": object_key,
            "content_length": content_length,
            "content_type": content_type,
            "checksum": checksum,
            "direct_requested": direct_requested,
        }
        return await self.store.create_upload(tenant_id, space_id, data)

    async def complete_upload(
        self, tenant_id: UUID, upload_id: UUID, checksum: str | None
    ) -> dict[str, Any]:
        upload = await self.store.get_upload(tenant_id, upload_id)
        if upload is None:
            raise ApiError("resource_not_found", "Upload not found", status_code=404)
        if upload.get("status") != "pending":
            raise ApiError("upload_verification_failed", "Upload not pending", status_code=409)
        return await self.store.complete_upload(tenant_id, upload_id, {"checksum": checksum})


@dataclass
class MultipartCommandService:
    store: SqlAlchemyFileStore

    async def create_multipart(
        self, tenant_id: UUID, principal_id: UUID, space_id: UUID,
        object_key: str, content_length: int, content_type: str,
    ) -> dict[str, Any]:
        data = {
            "principal_id": str(principal_id),
            "object_key": object_key,
            "content_length": content_length,
            "content_type": content_type,
        }
        return await self.store.create_multipart(tenant_id, space_id, data)

    async def add_part(
        self, tenant_id: UUID, principal_id: UUID, multipart_id: UUID,
        part_number: int, etag: str, content_length: int,
    ) -> dict[str, Any]:
        mp = await self.store.get_multipart(tenant_id, multipart_id)
        if mp is None:
            raise ApiError("resource_not_found", "Multipart not found", status_code=404)
        if mp.get("principal_id") != str(principal_id):
            raise ApiError("permission_denied", "Multipart belongs to different principal", status_code=403)
        return await self.store.confirm_multipart_part(
            tenant_id, multipart_id, part_number,
            {"etag": etag, "content_length": content_length},
        )

    async def complete(
        self, tenant_id: UUID, multipart_id: UUID, parts: list[dict[str, Any]]
    ) -> dict[str, Any]:
        mp = await self.store.get_multipart(tenant_id, multipart_id)
        if mp is None:
            raise ApiError("resource_not_found", "Multipart not found", status_code=404)
        if mp.get("status") != "pending":
            raise ApiError("multipart_invalid", "Multipart not pending", status_code=409)
        return await self.store.complete_multipart(tenant_id, multipart_id, {"parts": parts})

    async def abort(self, tenant_id: UUID, multipart_id: UUID) -> None:
        await self.store.abort_multipart(tenant_id, multipart_id)


@dataclass
class ObjectOperationService:
    store: SqlAlchemyFileStore

    async def create_operation(
        self, tenant_id: UUID, principal_id: UUID, space_id: UUID,
        operation_type: str, source_key: str | None, destination_key: str | None,
        keys: list[str] | None, idempotency_key: str,
    ) -> dict[str, Any]:
        data = {
            "principal_id": str(principal_id),
            "operation_type": operation_type,
            "source_key": source_key,
            "destination_key": destination_key,
            "keys": keys or [],
            "idempotency_key": idempotency_key,
        }
        return await self.store.create_operation(tenant_id, space_id, data)

    async def get_operation(self, tenant_id: UUID, operation_id: UUID) -> dict[str, Any]:
        result = await self.store.get_operation(tenant_id, operation_id)
        if result is None:
            raise ApiError("resource_not_found", "Operation not found", status_code=404)
        return result