"""File, upload, presigned download, and multipart application service."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from s3mp.common.errors import ApiError
from s3mp.files.application.auth_guard import FileAuthGuard
from s3mp.identity.domain.context import PrincipalContext


class FileStore(Protocol):
    async def list_files(self, tenant_id: UUID, space_id: UUID, prefix: str) -> list[dict[str, Any]]: ...
    async def get_file(self, tenant_id: UUID, space_id: UUID, file_id: UUID) -> dict[str, Any] | None: ...
    async def delete_file(self, tenant_id: UUID, space_id: UUID, file_id: UUID, *, idempotency_key: str | None = None, if_match: str | None = None) -> None: ...
    async def create_operation(self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...
    async def get_operation(self, tenant_id: UUID, op_id: UUID) -> dict[str, Any] | None: ...
    async def create_upload(self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...
    async def get_upload(self, tenant_id: UUID, upload_id: UUID) -> dict[str, Any] | None: ...
    async def complete_upload(self, tenant_id: UUID, upload_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...
    async def create_multipart(self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...
    async def set_multipart_provider_id(self, tenant_id: UUID, multipart_id: UUID, provider_upload_id: str) -> dict[str, Any]: ...
    async def get_multipart(self, tenant_id: UUID, multipart_id: UUID) -> dict[str, Any] | None: ...
    async def abort_multipart(self, tenant_id: UUID, multipart_id: UUID, *, idempotency_key: str | None = None) -> None: ...
    async def list_multipart_parts(self, tenant_id: UUID, multipart_id: UUID) -> list[dict[str, Any]]: ...
    async def create_multipart_part(self, tenant_id: UUID, multipart_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...
    async def confirm_multipart_part(self, tenant_id: UUID, multipart_id: UUID, part_number: int, data: dict[str, Any]) -> dict[str, Any]: ...
    async def complete_multipart(self, tenant_id: UUID, multipart_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...


class StorageSpaceStore(Protocol):
    async def get_space(self, tenant_id: UUID, space_id: UUID) -> dict[str, Any] | None: ...


class ObjectStorage(Protocol):
    async def put(self, key: str, body: bytes, content_type: str) -> object: ...
    async def head(self, key: str) -> object | None: ...
    async def delete(self, key: str) -> None: ...
    async def presign_get(self, key: str, expires_in: int) -> str: ...
    async def readiness_probe(self) -> None: ...
    # ── Multipart ──────────────────────────────────────────────────────────
    async def create_multipart_upload(self, key: str, content_type: str) -> str: ...
    async def upload_part(self, key: str, upload_id: str, part_number: int, body: bytes) -> dict[str, object]: ...
    async def complete_multipart_upload(self, key: str, upload_id: str, parts: list[dict[str, object]]) -> object: ...
    async def abort_multipart_upload(self, key: str, upload_id: str) -> None: ...
    async def list_parts(self, key: str, upload_id: str) -> list[dict[str, object]]: ...


@dataclass
class FileApplicationService:
    store: FileStore
    object_storage: ObjectStorage | None = None
    storage_store: StorageSpaceStore | None = None

    async def _resolve_space(self, tenant_id: UUID, space_id: UUID) -> dict[str, Any]:
        """Resolve storage space and validate tenant ownership."""
        if self.storage_store is None:
            raise ApiError("internal_error", "Storage store not configured", status_code=500)
        space = await self.storage_store.get_space(tenant_id, space_id)
        if space is None:
            raise ApiError("resource_not_found", "Storage space not found", status_code=404)
        return space

    def _physical_key(self, space: dict[str, Any], relative_key: str) -> str:
        """Build the full S3 key from storage space root prefix + object key."""
        root = (space.get("root_prefix") or "").strip("/")
        return f"{root}/{relative_key}" if root else relative_key

    # ── Files ──────────────────────────────────────────────────────────────

    async def list_files(self, ctx: PrincipalContext, space_id: str, prefix: str) -> list[dict[str, Any]]:
        return await self.store.list_files(ctx.tenant_id, UUID(space_id), prefix)

    async def get_file(self, ctx: PrincipalContext, space_id: str, file_id: str) -> dict[str, Any]:
        result = await self.store.get_file(ctx.tenant_id, UUID(space_id), UUID(file_id))
        if result is None:
            raise ApiError("resource_not_found", "File not found", status_code=404)
        return result

    async def delete_file(
        self, ctx: PrincipalContext, space_id: str, file_id: str,
        idempotency_key: str | None = None, if_match: str | None = None,
    ) -> dict[str, Any]:
        if self.object_storage is not None:
            record = await self.store.get_file(ctx.tenant_id, UUID(space_id), UUID(file_id))
            if record:
                await self.object_storage.delete(record["object_key"])
        await self.store.delete_file(ctx.tenant_id, UUID(space_id), UUID(file_id),
                                     idempotency_key=idempotency_key, if_match=if_match)
        return {"status": "deleted"}

    async def create_file_operation(
        self, ctx: PrincipalContext, space_id: str, body: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        data = {
            "principal_id": str(ctx.principal_id),
            "operation_type": body.operation_type,
            "source_key": body.source_key,
            "destination_key": body.destination_key,
            "keys": body.keys,
            "idempotency_key": idempotency_key or str(uuid4()),
        }
        return await self.store.create_operation(ctx.tenant_id, UUID(space_id), data)

    async def get_file_operation(self, ctx: PrincipalContext, operation_id: str) -> dict[str, Any]:
        result = await self.store.get_operation(ctx.tenant_id, UUID(operation_id))
        if result is None:
            raise ApiError("resource_not_found", "Operation not found", status_code=404)
        return result

    # ── Uploads ────────────────────────────────────────────────────────────

    async def create_upload(
        self, ctx: PrincipalContext, space_id: str, body: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        FileAuthGuard.validate_canonical_key(body.object_key)
        space = await self._resolve_space(ctx.tenant_id, UUID(space_id))
        physical_key = self._physical_key(space, body.object_key)
        data = {
            "principal_id": str(ctx.principal_id),
            "object_key": physical_key,
            "content_length": body.content_length,
            "content_type": body.content_type,
            "checksum": body.checksum,
            "direct_requested": body.direct_requested,
            "idempotency_key": idempotency_key,
        }
        return await self.store.create_upload(ctx.tenant_id, UUID(space_id), data)

    async def get_upload(self, ctx: PrincipalContext, upload_id: str) -> dict[str, Any]:
        result = await self.store.get_upload(ctx.tenant_id, UUID(upload_id))
        if result is None:
            raise ApiError("resource_not_found", "Upload not found", status_code=404)
        FileAuthGuard.check_ownership(result, ctx)
        return result

    async def proxy_upload_content(
        self, ctx: PrincipalContext, upload_id: str,
        body: bytes, content_length: int, content_type: str,
    ) -> None:
        record = await self.store.get_upload(ctx.tenant_id, UUID(upload_id))
        if record is None:
            raise ApiError("resource_not_found", "Upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        if record.get("content_length") != content_length:
            raise ApiError("upload_verification_failed", "Content-Length mismatch", status_code=409)
        if self.object_storage is not None:
            await self.object_storage.put(
                record["object_key"], body, content_type
            )

    async def complete_upload(
        self, ctx: PrincipalContext, upload_id: str, body: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        record = await self.store.get_upload(ctx.tenant_id, UUID(upload_id))
        if record is None:
            raise ApiError("resource_not_found", "Upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        if record.get("status") != "pending":
            raise ApiError("upload_verification_failed", "Upload not pending", status_code=409)
        if self.object_storage is not None:
            obj = await self.object_storage.head(record["object_key"])
            if obj is None:
                raise ApiError("upload_verification_failed", "Object not found in storage", status_code=409)
            if getattr(obj, "key", record["object_key"]) != record["object_key"]:
                raise ApiError("upload_verification_failed", "Object key mismatch", status_code=409)
            if getattr(obj, "content_length", None) != record["content_length"]:
                raise ApiError("upload_verification_failed", "Object size mismatch", status_code=409)
            actual_type = getattr(obj, "content_type", None)
            if actual_type and actual_type.lower() != str(record["content_type"]).lower():
                raise ApiError("upload_verification_failed", "Object content type mismatch", status_code=409)
            requested_checksum = body.checksum or record.get("checksum")
            actual_checksum = getattr(obj, "checksum_sha256", None)
            if requested_checksum and actual_checksum and requested_checksum not in {actual_checksum, f"sha256:{actual_checksum}"}:
                raise ApiError("upload_verification_failed", "Object checksum mismatch", status_code=409)
            provider_etag = getattr(obj, "etag", None)
            provider_version = getattr(obj, "version_id", None)
        else:
            provider_etag = None
            provider_version = None
        file_data = {
            "tenant_id": str(ctx.tenant_id),
            "storage_space_id": record["storage_space_id"],
            "object_key": record["object_key"],
            "content_length": record["content_length"],
            "content_type": record["content_type"],
            "checksum": record.get("checksum"),
            "etag": provider_etag,
            "version_id": provider_version,
            "idempotency_key": idempotency_key,
        }
        return await self.store.complete_upload(ctx.tenant_id, UUID(upload_id), file_data)

    async def create_presigned_download(
        self, ctx: PrincipalContext, space_id: str, body: Any
    ) -> dict[str, Any]:
        if self.object_storage is None:
            raise ApiError("internal_error", "Object storage is not configured", status_code=500)
        # Look up file by file_id (tenant-scoped) instead of accepting raw object_key
        file_record = await self.store.get_file(ctx.tenant_id, UUID(space_id), UUID(body.file_id))
        if file_record is None:
            raise ApiError("resource_not_found", "File not found", status_code=404)
        url = await self.object_storage.presign_get(file_record["object_key"], body.ttl_seconds)
        return {
            "method": "GET",
            "url": url,
            "file_id": body.file_id,
            "expires_in": body.ttl_seconds,
        }

    # ── Multipart ──────────────────────────────────────────────────────────

    async def create_multipart_upload(
        self, ctx: PrincipalContext, space_id: str, body: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        FileAuthGuard.validate_canonical_key(body.object_key)
        space = await self._resolve_space(ctx.tenant_id, UUID(space_id))
        physical_key = self._physical_key(space, body.object_key)
        data = {
            "principal_id": str(ctx.principal_id),
            "object_key": physical_key,
            "content_length": body.content_length,
            "content_type": body.content_type,
            "idempotency_key": idempotency_key,
        }
        record = await self.store.create_multipart(ctx.tenant_id, UUID(space_id), data)
        if self.object_storage is None:
            raise ApiError("storage_capability_unsupported", "Multipart storage is not configured", status_code=422)
        try:
            provider_upload_id = await self.object_storage.create_multipart_upload(
                physical_key, body.content_type
            )
            return await self.store.set_multipart_provider_id(
                ctx.tenant_id, UUID(record["id"]), provider_upload_id
            )
        except Exception:
            await self.store.abort_multipart(ctx.tenant_id, UUID(record["id"]))
            raise

    async def get_multipart_upload(self, ctx: PrincipalContext, multipart_id: str) -> dict[str, Any]:
        result = await self.store.get_multipart(ctx.tenant_id, UUID(multipart_id))
        if result is None:
            raise ApiError("resource_not_found", "Multipart upload not found", status_code=404)
        FileAuthGuard.check_ownership(result, ctx)
        return result

    async def abort_multipart_upload(
        self, ctx: PrincipalContext, multipart_id: str,
        idempotency_key: str | None = None,
    ) -> None:
        record = await self.store.get_multipart(ctx.tenant_id, UUID(multipart_id))
        if record is None:
            raise ApiError("resource_not_found", "Multipart upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        await self.store.abort_multipart(ctx.tenant_id, UUID(multipart_id),
                                         idempotency_key=idempotency_key)

    async def list_multipart_parts(self, ctx: PrincipalContext, multipart_id: str) -> list[dict[str, Any]]:
        record = await self.store.get_multipart(ctx.tenant_id, UUID(multipart_id))
        if record is None:
            raise ApiError("resource_not_found", "Multipart upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        return await self.store.list_multipart_parts(ctx.tenant_id, UUID(multipart_id))

    async def create_multipart_part(
        self, ctx: PrincipalContext, multipart_id: str, body: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        record = await self.store.get_multipart(ctx.tenant_id, UUID(multipart_id))
        if record is None:
            raise ApiError("resource_not_found", "Multipart upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        data = {"part_number": body.part_number, "idempotency_key": idempotency_key}
        return await self.store.create_multipart_part(ctx.tenant_id, UUID(multipart_id), data)

    async def confirm_multipart_part(
        self, ctx: PrincipalContext, multipart_id: str, part_number: int, body: Any
    ) -> dict[str, Any]:
        record = await self.store.get_multipart(ctx.tenant_id, UUID(multipart_id))
        if record is None:
            raise ApiError("resource_not_found", "Multipart upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        data = {"etag": body.etag, "content_length": body.content_length}
        return await self.store.confirm_multipart_part(
            ctx.tenant_id, UUID(multipart_id), part_number, data
        )

    async def complete_multipart_upload(
        self, ctx: PrincipalContext, multipart_id: str, body: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        record = await self.store.get_multipart(ctx.tenant_id, UUID(multipart_id))
        if record is None:
            raise ApiError("resource_not_found", "Multipart upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        provider_upload_id = record.get("provider_upload_id")
        if not provider_upload_id or self.object_storage is None:
            raise ApiError("storage_capability_unsupported", "Multipart provider session is unavailable", status_code=422)
        stored_parts = await self.store.list_multipart_parts(ctx.tenant_id, UUID(multipart_id))
        stored_by_number = {int(p["part_number"]): p for p in stored_parts}
        requested_numbers = [int(p.part_number) for p in body.parts]
        if requested_numbers != sorted(set(requested_numbers)):
            raise ApiError("multipart_parts_invalid", "Multipart parts must be unique and ordered", status_code=409)
        provider_parts: list[dict[str, object]] = []
        total_size = 0
        for part in body.parts:
            stored = stored_by_number.get(part.part_number)
            if stored is None or stored.get("etag") != part.etag:
                raise ApiError("multipart_parts_invalid", "Multipart part does not match stored metadata", status_code=409)
            provider_parts.append({"part_number": part.part_number, "etag": part.etag})
            total_size += int(stored.get("content_length", 0))
        if total_size != int(record["content_length"]):
            raise ApiError("multipart_parts_invalid", "Multipart size does not match declaration", status_code=409)
        metadata = await self.object_storage.complete_multipart_upload(
            record["object_key"], provider_upload_id, provider_parts
        )
        if getattr(metadata, "key", record["object_key"]) != record["object_key"] or getattr(metadata, "content_length", None) != total_size:
            raise ApiError("upload_verification_failed", "Completed multipart object metadata mismatch", status_code=409)
        data = {
            "parts": provider_parts,
            "content_length": total_size,
            "content_type": getattr(metadata, "content_type", record["content_type"]),
            "etag": getattr(metadata, "etag", None),
            "idempotency_key": idempotency_key,
        }
        return await self.store.complete_multipart(ctx.tenant_id, UUID(multipart_id), data)
