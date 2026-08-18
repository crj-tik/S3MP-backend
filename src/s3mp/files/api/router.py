"""Files, uploads, presigned downloads, and multipart HTTP endpoints."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Body, Header, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.application.idempotency import IdempotencyGuard
from s3mp.common.errors import ApiError
from s3mp.files.domain.file_status import FileObjectStatus
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Files", "Uploads", "Multipart"])


# ── DTOs ──────────────────────────────────────────────────────────────────────


class FileOperationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_type: str = Field(min_length=1, max_length=32)
    source_key: str | None = Field(default=None, max_length=1024)
    destination_key: str | None = Field(default=None, max_length=1024)
    keys: list[str] | None = Field(default=None)


class DirectUploadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_key: str = Field(min_length=1, max_length=1024)
    content_length: int = Field(ge=0)
    content_type: str = Field(min_length=1, max_length=255)
    checksum: str | None = Field(default=None, max_length=512)


class UploadComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checksum: str | None = Field(default=None, max_length=512)


class PresignedDownloadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str = Field(min_length=1, max_length=64)
    ttl_seconds: int = Field(default=900, ge=30, le=3600)


class MultipartCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_key: str = Field(min_length=1, max_length=1024)
    content_length: int = Field(ge=0)
    content_type: str = Field(min_length=1, max_length=255)


class MultipartPartRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    part_number: int
    etag: str
    content_length: int


class FileObjectRuntime(BaseModel):
    """已提交文件的公开元数据；不包含对象存储物理路径或鉴权证据。"""

    id: str
    storage_space_id: str | None = None
    object_key: str
    content_length: int | None = None
    content_type: str | None = None
    status: str | None = None
    etag: str | None = None
    checksum: str | None = None
    created_at: str | None = None


class UploadSessionRuntime(BaseModel):
    """上传会话响应，`id` 用于后续内容上传和完成确认。"""

    id: str
    storage_space_id: str | None = None
    object_key: str | None = None
    content_length: int | None = None
    content_type: str | None = None
    status: str | None = None
    expires_at: str | None = None
    ingestion_id: str | None = None


class DirectUploadSessionRuntime(UploadSessionRuntime):
    mode: str = "direct"
    method: str = "PUT"
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)


class MultipartUploadRuntime(UploadSessionRuntime):
    mode: str = "multipart"
    part_size: int = Field(default=8 * 1024 * 1024, ge=1)


class FileOperationRuntime(BaseModel):
    id: str
    operation_type: str | None = None
    status: str | None = None
    source_key: str | None = None
    destination_key: str | None = None
    keys: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    attempt_count: int = 0
    next_retry_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None


class IngestionCommitResult(BaseModel):
    """上传提交结果；`file_object` 存在时表示文件元数据已写入系统。"""

    id: str
    status: str | None = None
    storage_space_id: str | None = None
    file_object: FileObjectRuntime | None = None
    etag: str | None = None


class MultipartCompleteRuntime(BaseModel):
    """分片合并结果；成功后可选返回已入库的文件元数据。"""

    id: str
    status: str | None = None
    storage_space_id: str | None = None
    object_key: str | None = None
    content_length: int | None = None
    content_type: str | None = None
    etag: str | None = None
    file_object: FileObjectRuntime | None = None


class MultipartCompletePart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_number: int = Field(ge=1, le=10000)
    etag: str = Field(min_length=1, max_length=512)


class MultipartComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parts: list[MultipartCompletePart] = Field(min_length=1)


class IngestionProvenanceEvent(BaseModel):
    id: str
    event_type: str
    occurred_at: str | None = None


class IngestionProvenanceFile(BaseModel):
    id: str
    status: str
    content_length: int
    created_at: str | None = None
    deleted_at: str | None = None


class IngestionProvenanceAdjustment(BaseModel):
    id: str
    quota_id: str
    delta_bytes: int
    reason: str
    created_at: str | None = None


class IngestionProvenance(BaseModel):
    ingestion: dict[str, Any]
    events: list[IngestionProvenanceEvent]
    file_object: IngestionProvenanceFile | None = None
    quota_adjustments: list[IngestionProvenanceAdjustment]


# ── Dependencies ──────────────────────────────────────────────────────────────


def _context(request: Request) -> PrincipalContext:
    context = getattr(request.state, "principal_context", None)
    if not isinstance(context, PrincipalContext):
        raise ApiError("authentication_required", "Authentication required", status_code=401)
    return context


def _file_svc(request: Request) -> Any:
    # Authenticate before probing application wiring.  This prevents an
    # account-only browser session from observing a configuration failure on
    # tenant data-plane routes and keeps every file endpoint fail-closed.
    _context(request)
    svc = getattr(request.app.state, "file_service", None)
    if svc is None:
        raise ApiError("internal_error", "File service is not configured", status_code=500)
    return svc


def _idempotency_key(value: str | None) -> str:
    return IdempotencyGuard.validate_key(value)


# ── Files ─────────────────────────────────────────────────────────────────────


@router.get(
    "/storage_spaces/{space_id}/files",
    response_model=list[FileObjectRuntime],
    operation_id="list_files",
)
async def list_files(
    request: Request,
    space_id: str = Path(min_length=1),
    prefix: str | None = None,
    status: Annotated[FileObjectStatus, Query()] = FileObjectStatus.AVAILABLE,
) -> list[FileObjectRuntime]:
    return [
        FileObjectRuntime.model_validate(item)
        for item in await _file_svc(request).list_files(
            _context(request), space_id, prefix or "", status
        )
    ]


@router.get(
    "/storage_spaces/{space_id}/files/{file_id}",
    response_model=FileObjectRuntime,
    operation_id="get_file",
)
async def get_file(
    request: Request,
    space_id: str = Path(min_length=1),
    file_id: str = Path(min_length=1),
) -> FileObjectRuntime:
    return FileObjectRuntime.model_validate(
        await _file_svc(request).get_file(_context(request), space_id, file_id)
    )


@router.delete(
    "/storage_spaces/{space_id}/files/{file_id}", status_code=202, operation_id="delete_file"
)
async def delete_file(
    request: Request,
    space_id: str = Path(min_length=1),
    file_id: str = Path(min_length=1),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _file_svc(request).delete_file(
        _context(request),
        space_id,
        file_id,
        idempotency_key=_idempotency_key(idempotency_key),
        if_match=if_match,
    )


@router.post(
    "/storage_spaces/{space_id}/file_operations",
    status_code=202,
    response_model=FileOperationRuntime,
    operation_id="create_file_operation",
)
async def create_file_operation(
    request: Request,
    body: FileOperationCreate,
    space_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> FileOperationRuntime:
    return FileOperationRuntime.model_validate(
        await _file_svc(request).create_file_operation(
            _context(request), space_id, body, idempotency_key=_idempotency_key(idempotency_key)
        )
    )


@router.get(
    "/file_operations/{operation_id}",
    response_model=FileOperationRuntime,
    operation_id="get_file_operation",
)
async def get_file_operation(
    request: Request,
    operation_id: str = Path(min_length=1),
) -> FileOperationRuntime:
    return FileOperationRuntime.model_validate(
        await _file_svc(request).get_file_operation(_context(request), operation_id)
    )


# ── Uploads ───────────────────────────────────────────────────────────────────


@router.get(
    "/ingestions/{ingestion_id}/provenance",
    response_model=IngestionProvenance,
    operation_id="get_ingestion_provenance",
)
async def get_ingestion_provenance(
    request: Request,
    ingestion_id: str = Path(min_length=1),
) -> IngestionProvenance:
    return IngestionProvenance.model_validate(
        await _file_svc(request).get_ingestion_provenance(_context(request), ingestion_id)
    )


@router.post(
    "/storage_spaces/{space_id}/direct_uploads",
    status_code=201,
    response_model=DirectUploadSessionRuntime,
    operation_id="create_direct_upload",
)
async def create_direct_upload(
    request: Request,
    body: DirectUploadCreate,
    space_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DirectUploadSessionRuntime:
    return DirectUploadSessionRuntime.model_validate(
        await _file_svc(request).create_direct_upload(
            _context(request), space_id, body, idempotency_key=_idempotency_key(idempotency_key)
        )
    )


@router.get(
    "/direct_uploads/{upload_id}",
    response_model=DirectUploadSessionRuntime,
    operation_id="get_direct_upload",
)
async def get_direct_upload(
    request: Request,
    upload_id: str = Path(min_length=1),
) -> DirectUploadSessionRuntime:
    return DirectUploadSessionRuntime.model_validate(
        await _file_svc(request).get_direct_upload(_context(request), upload_id)
    )


@router.post(
    "/direct_uploads/{upload_id}/completion",
    response_model=IngestionCommitResult,
    operation_id="complete_direct_upload",
)
async def complete_direct_upload(
    request: Request,
    body: UploadComplete,
    upload_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IngestionCommitResult:
    return IngestionCommitResult.model_validate(
        await _file_svc(request).complete_direct_upload(
            _context(request), upload_id, body, idempotency_key=_idempotency_key(idempotency_key)
        )
    )


@router.post(
    "/storage_spaces/{space_id}/presigned_downloads",
    status_code=201,
    operation_id="create_presigned_download",
)
async def create_presigned_download(
    request: Request,
    body: PresignedDownloadCreate,
    space_id: str = Path(min_length=1),
) -> Any:
    return await _file_svc(request).create_presigned_download(_context(request), space_id, body)


# ── Multipart ─────────────────────────────────────────────────────────────────


@router.post(
    "/storage_spaces/{space_id}/multipart_uploads",
    status_code=201,
    response_model=MultipartUploadRuntime,
    operation_id="create_multipart_upload",
)
async def create_multipart_upload(
    request: Request,
    body: MultipartCreate,
    space_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MultipartUploadRuntime:
    return MultipartUploadRuntime.model_validate(
        await _file_svc(request).create_multipart_upload(
            _context(request), space_id, body, idempotency_key=_idempotency_key(idempotency_key)
        )
    )


@router.get(
    "/multipart_uploads/{multipart_id}",
    response_model=MultipartUploadRuntime,
    operation_id="get_multipart_upload",
)
async def get_multipart_upload(
    request: Request,
    multipart_id: str = Path(min_length=1),
) -> MultipartUploadRuntime:
    return MultipartUploadRuntime.model_validate(
        await _file_svc(request).get_multipart_upload(_context(request), multipart_id)
    )


@router.delete(
    "/multipart_uploads/{multipart_id}", status_code=204, operation_id="abort_multipart_upload"
)
async def abort_multipart_upload(
    request: Request,
    multipart_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> None:
    await _file_svc(request).abort_multipart_upload(
        _context(request), multipart_id, idempotency_key=_idempotency_key(idempotency_key)
    )


@router.get(
    "/multipart_uploads/{multipart_id}/parts",
    response_model=list[MultipartPartRuntime],
    operation_id="list_multipart_parts",
)
async def list_multipart_parts(
    request: Request,
    multipart_id: str = Path(min_length=1),
) -> list[MultipartPartRuntime]:
    return cast(
        list[MultipartPartRuntime],
        await _file_svc(request).list_multipart_parts(_context(request), multipart_id),
    )


@router.put(
    "/multipart_uploads/{multipart_id}/parts/{part_number}",
    response_model=MultipartPartRuntime,
    operation_id="upload_multipart_part",
)
async def upload_multipart_part(
    request: Request,
    multipart_id: str = Path(min_length=1),
    part_number: int = Path(ge=1, le=10000),
    content_length: int = Header(alias="Content-Length"),
    body: bytes = Body(..., media_type="application/octet-stream"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MultipartPartRuntime:
    return MultipartPartRuntime.model_validate(
        await _file_svc(request).upload_multipart_part(
            _context(request),
            multipart_id,
            part_number,
            body,
            content_length,
            idempotency_key=_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/multipart_uploads/{multipart_id}/completion",
    response_model=MultipartCompleteRuntime,
    operation_id="complete_multipart_upload",
)
async def complete_multipart_upload(
    request: Request,
    body: MultipartComplete,
    multipart_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MultipartCompleteRuntime:
    return MultipartCompleteRuntime.model_validate(
        await _file_svc(request).complete_multipart_upload(
            _context(request), multipart_id, body, idempotency_key=_idempotency_key(idempotency_key)
        )
    )
