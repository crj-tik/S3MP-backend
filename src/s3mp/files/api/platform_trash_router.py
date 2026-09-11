"""Platform management routes for retained deletion records."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from s3mp.common.api.dependencies import application_service
from s3mp.files.application.trash_service import PlatformTrashService
from s3mp.platform.api.dependencies import platform_permission
from s3mp.platform.domain.context import PlatformContext

router = APIRouter(prefix="/api/v1/platform/file-trash", tags=["Platform file trash"])
trash_service = application_service("platform_trash_service")


class TrashRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    file_id: UUID
    storage_space_id: UUID
    application_id: UUID | None = None
    original_relative_key: str
    content_length: int
    content_type: str
    etag: str | None = None
    deleted_by: UUID | None = None
    deleted_at: datetime
    purge_due_at: datetime
    status: str
    attempt_count: int
    next_retry_at: datetime | None = None
    failure_reason: str | None = None
    purged_at: datetime | None = None


class TrashRecordPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TrashRecordResponse]
    next_cursor: UUID | None = None


ReadContext = Annotated[
    PlatformContext, platform_permission("platform.file_trash.read", "list_platform_file_trash")
]
DownloadContext = Annotated[
    PlatformContext,
    platform_permission("platform.file_trash.read", "download_platform_file_trash"),
]


@router.get("", response_model=TrashRecordPage, operation_id="list_platform_file_trash")
async def list_platform_file_trash(
    _context: ReadContext,
    service: Annotated[PlatformTrashService, trash_service],
    tenant_id: UUID | None = None,
    storage_space_id: UUID | None = None,
    status: str | None = Query(default=None, max_length=32),
    cursor: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> TrashRecordPage:
    records = await service.list_records(
        tenant_id=tenant_id,
        storage_space_id=storage_space_id,
        status=status,
        limit=limit + 1,
        after_id=cursor,
    )
    next_cursor = UUID(records.pop()["id"]) if len(records) > limit else None
    return TrashRecordPage(
        items=[TrashRecordResponse.model_validate(item) for item in records],
        next_cursor=next_cursor,
    )


@router.get(
    "/{deletion_id}", response_model=TrashRecordResponse, operation_id="get_platform_file_trash"
)
async def get_platform_file_trash(
    deletion_id: UUID,
    _context: ReadContext,
    service: Annotated[PlatformTrashService, trash_service],
) -> TrashRecordResponse:
    return TrashRecordResponse.model_validate(await service.get_record(deletion_id))


@router.post("/{deletion_id}/download", operation_id="download_platform_file_trash")
async def download_platform_file_trash(
    deletion_id: UUID,
    _context: DownloadContext,
    service: Annotated[PlatformTrashService, trash_service],
    expires_in: int = Query(default=300, ge=60, le=3600),
) -> dict[str, str | int]:
    return {
        "url": await service.download(_context, deletion_id, expires_in),
        "expires_in": expires_in,
    }
