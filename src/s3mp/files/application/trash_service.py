"""Platform-only access to retained deletion records and trash objects."""

from typing import Any
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.files.infrastructure.repositories import SqlAlchemyFileStore
from s3mp.platform.domain.context import PlatformContext
from s3mp.storage.domain.policy import ProviderTarget


class PlatformTrashService:
    def __init__(self, store: SqlAlchemyFileStore, object_storage: Any) -> None:
        self.store = store
        self.object_storage = object_storage

    async def list_records(self, **filters: Any) -> list[dict[str, Any]]:
        return await self.store.list_deletion_records(**filters)

    async def get_record(self, deletion_id: UUID) -> dict[str, Any]:
        record = await self.store.get_deletion_record(deletion_id)
        if record is None:
            raise ApiError("resource_not_found", "Deletion record not found", 404)
        return record

    async def download(self, _context: PlatformContext, deletion_id: UUID, expires_in: int) -> str:
        record = await self.store.get_deletion_record_internal(deletion_id)
        if record is None or record["status"] not in {"retained", "purging"}:
            raise ApiError("resource_not_found", "Retained file not found", 404)
        space = await self.store.get_storage_space_for_deletion(
            UUID(record["tenant_id"]), UUID(record["storage_space_id"])
        )
        if space is None:
            raise ApiError("resource_not_found", "Storage space not found", 404)
        target = ProviderTarget(bucket=space["bucket"], key=record["trash_physical_key"])
        if await self.object_storage.head(target) is None:
            raise ApiError("resource_not_found", "Retained file is unavailable", 404)
        return await self.object_storage.presign_get(target, expires_in)
