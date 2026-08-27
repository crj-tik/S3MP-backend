"""Files, uploads, presigned downloads, and multipart HTTP endpoints."""

from datetime import datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Body, Header, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from s3mp.common.api.dependencies import management_permission
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


class FileRenameCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_key: str = Field(min_length=1, max_length=1024)


class DirectUploadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_key: str = Field(min_length=1, max_length=1024)
    content_length: int = Field(ge=0)
    content_type: str = Field(min_length=1, max_length=255)
    checksum: str | None = Field(default=None, max_length=512)
    metadata: JsonValue | None = Field(
        default=None, description="应用提供的 JSON 元数据；平台不解析其业务含义。"
    )
    expires_at: datetime = Field(
        description="资源或授权的失效时间，采用 Asia/Shanghai（UTC+08:00）格式。"
    )


class UploadPrecheckCreate(BaseModel):
    """Caller-proposed name and size before creating an upload session."""

    model_config = ConfigDict(extra="forbid")
    object_key: str = Field(min_length=1, max_length=1024)
    content_length: int = Field(ge=0)


class UploadPrecheckRuntime(BaseModel):
    """Advisory result; upload completion remains the authoritative collision check."""

    object_key: str
    content_length: int = Field(ge=0)
    exists: bool


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
    metadata: JsonValue | None = Field(
        default=None, description="应用提供的 JSON 元数据；平台不解析其业务含义。"
    )
    expires_at: datetime = Field(
        description="资源或授权的失效时间，采用 Asia/Shanghai（UTC+08:00）格式。"
    )


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
    metadata: JsonValue | None = None
    created_at: str | None = None


class FileDeletionResult(BaseModel):
    status: str
    purge_due_at: str | None = None


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
    source_file_id: str | None = None
    result_file_id: str | None = None
    keys: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    attempt_count: int = 0
    next_retry_at: str | None = None
    completed_at: str | None = None
    created_at: str | None = None


class RenameAcceptedFile(BaseModel):
    id: str
    object_key: str
    status: str = "renaming"


class FileRenameAccepted(BaseModel):
    operation_id: str
    status: str
    file: RenameAcceptedFile


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
    deprecated=True,
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


@router.post(
    "/storage_spaces/{space_id}/upload_prechecks",
    response_model=UploadPrecheckRuntime,
    operation_id="precheck_upload",
    deprecated=True,
)
async def precheck_upload(
    request: Request, body: UploadPrecheckCreate, space_id: str = Path(min_length=1)
) -> UploadPrecheckRuntime:
    return UploadPrecheckRuntime.model_validate(
        await _file_svc(request).precheck_upload(
            _context(request), space_id, body.object_key, body.content_length
        )
    )


@router.get(
    "/storage_spaces/{space_id}/files/{file_id}",
    response_model=FileObjectRuntime,
    operation_id="get_file",
    deprecated=True,
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
    "/storage_spaces/{space_id}/files/{file_id}",
    status_code=202,
    response_model=FileDeletionResult,
    operation_id="delete_file",
    deprecated=True,
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
    "/storage_spaces/{space_id}/files/{file_id}/restore",
    response_model=FileObjectRuntime,
    operation_id="restore_file",
    deprecated=True,
    dependencies=[management_permission("restore_file")],
)
async def restore_file(
    request: Request,
    space_id: str = Path(min_length=1),
    file_id: str = Path(min_length=1),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> FileObjectRuntime:
    return FileObjectRuntime.model_validate(
        await _file_svc(request).restore_file(
            _context(request),
            space_id,
            file_id,
            idempotency_key=_idempotency_key(idempotency_key),
            if_match=if_match,
        )
    )


@router.post(
    "/storage_spaces/{space_id}/file_operations",
    status_code=202,
    response_model=FileOperationRuntime,
    operation_id="create_file_operation",
    deprecated=True,
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
    deprecated=True,
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
    application_code: str | None = Query(default=None, min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IngestionCommitResult:
    if _context(request).subject_kind == "application":
        if application_code is None:
            raise ApiError("validation_failed", "application_code is required", status_code=422)
        await _application_api_context(request, application_code)
    return IngestionCommitResult.model_validate(
        await _file_svc(request).complete_direct_upload(
            _context(request), upload_id, body, idempotency_key=_idempotency_key(idempotency_key)
        )
    )


@router.post(
    "/storage_spaces/{space_id}/presigned_downloads",
    status_code=201,
    operation_id="create_presigned_download",
    deprecated=True,
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
    deprecated=True,
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


# ── Application-context file entry points ────────────────────────────────────


async def _implicit_space_id(request: Request, application_id: UUID | None = None) -> str:
    """Resolve the app directory from its API key, or a human-selected app code."""
    context = _context(request)
    if context.subject_kind == "application":
        if application_id is not None:
            raise ApiError(
                "permission_denied", "API keys must use the application API route", status_code=403
            )
        if context.application_id is None:
            raise ApiError(
                "permission_denied", "Application credential is not bound", status_code=403
            )
        space = await _file_svc(request).resolve_application_space(context, context.application_id)
    elif application_id is not None:
        space = await _file_svc(request).resolve_application_space(context, application_id)
    else:
        raise ApiError("permission_denied", "Application API key is required", status_code=403)
    return str(space["id"])


async def _application_api_context(request: Request, application_code: str) -> None:
    """Use the Key application as target and the code application as audit actor."""
    request.state.principal_context = await _file_svc(request).application_actor_context(
        _context(request), application_code
    )


@router.get(
    "/applications/{application_id}/files",
    response_model=list[FileObjectRuntime],
    operation_id="list_application_files",
)
async def list_application_files(
    request: Request,
    application_id: UUID,
    prefix: str | None = None,
    status: Annotated[FileObjectStatus, Query()] = FileObjectStatus.AVAILABLE,
) -> list[FileObjectRuntime]:
    return await list_files(
        request, await _implicit_space_id(request, application_id), prefix, status
    )


@router.get(
    "/application/files",
    response_model=list[FileObjectRuntime],
    operation_id="list_current_application_files",
)
async def list_current_application_files(
    request: Request,
    application_code: str = Query(min_length=1),
    prefix: str | None = None,
    status: Annotated[FileObjectStatus, Query()] = FileObjectStatus.AVAILABLE,
) -> list[FileObjectRuntime]:
    await _application_api_context(request, application_code)
    return await list_files(request, await _implicit_space_id(request), prefix, status)


@router.post(
    "/applications/{application_id}/upload_prechecks",
    response_model=UploadPrecheckRuntime,
    operation_id="precheck_application_upload",
)
async def precheck_application_upload(
    request: Request, application_id: UUID, body: UploadPrecheckCreate
) -> UploadPrecheckRuntime:
    return await precheck_upload(request, body, await _implicit_space_id(request, application_id))


@router.post(
    "/application/upload_prechecks",
    response_model=UploadPrecheckRuntime,
    operation_id="precheck_current_application_upload",
)
async def precheck_current_application_upload(
    request: Request,
    body: UploadPrecheckCreate,
    application_code: str = Query(min_length=1),
) -> UploadPrecheckRuntime:
    await _application_api_context(request, application_code)
    return await precheck_upload(request, body, await _implicit_space_id(request))


@router.get(
    "/applications/{application_id}/files/{file_id}",
    response_model=FileObjectRuntime,
    operation_id="get_application_file",
)
async def get_application_file(
    request: Request, application_id: UUID, file_id: str
) -> FileObjectRuntime:
    return await get_file(request, await _implicit_space_id(request, application_id), file_id)


@router.get(
    "/application/files/{file_id}",
    response_model=FileObjectRuntime,
    operation_id="get_current_application_file",
)
async def get_current_application_file(
    request: Request, file_id: str, application_code: str = Query(min_length=1)
) -> FileObjectRuntime:
    await _application_api_context(request, application_code)
    return await get_file(request, await _implicit_space_id(request), file_id)


@router.delete(
    "/applications/{application_id}/files/{file_id}",
    status_code=202,
    operation_id="delete_application_file",
)
async def delete_application_file(
    request: Request,
    application_id: UUID,
    file_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await delete_file(
        request,
        await _implicit_space_id(request, application_id),
        file_id,
        if_match,
        idempotency_key,
    )


@router.delete(
    "/application/files/{file_id}",
    status_code=202,
    operation_id="delete_current_application_file",
)
async def delete_current_application_file(
    request: Request,
    file_id: str,
    application_code: str = Query(min_length=1),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    await _application_api_context(request, application_code)
    return await delete_file(
        request, await _implicit_space_id(request), file_id, if_match, idempotency_key
    )


@router.post(
    "/application/files/{file_id}/rename",
    status_code=202,
    response_model=FileRenameAccepted,
    operation_id="rename_current_application_file",
)
async def rename_current_application_file(
    request: Request,
    file_id: str,
    body: FileRenameCreate,
    application_code: str = Query(min_length=1),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> FileRenameAccepted:
    await _application_api_context(request, application_code)
    result = await _file_svc(request).rename_file(
        _context(request),
        await _implicit_space_id(request),
        file_id,
        body.object_key,
        if_match=if_match,
        idempotency_key=_idempotency_key(idempotency_key),
    )
    return FileRenameAccepted(
        operation_id=result["id"],
        status=str(result.get("status") or "pending"),
        file=RenameAcceptedFile(
            id=str(result["result_file_id"]), object_key=body.object_key, status="renaming"
        ),
    )


@router.get(
    "/application/file_operations/{operation_id}",
    response_model=FileOperationRuntime,
    operation_id="get_current_application_file_operation",
)
async def get_current_application_file_operation(
    request: Request,
    operation_id: str,
    application_code: str = Query(min_length=1),
) -> FileOperationRuntime:
    await _application_api_context(request, application_code)
    return FileOperationRuntime.model_validate(
        await _file_svc(request).get_file_operation(_context(request), operation_id)
    )


@router.post(
    "/applications/{application_id}/file_operations",
    status_code=202,
    response_model=FileOperationRuntime,
    operation_id="create_application_file_operation",
)
async def create_application_file_operation(
    request: Request,
    application_id: UUID,
    body: FileOperationCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> FileOperationRuntime:
    return await create_file_operation(
        request,
        body,
        await _implicit_space_id(request, application_id),
        idempotency_key,
    )


@router.post(
    "/application/file_operations",
    status_code=202,
    response_model=FileOperationRuntime,
    operation_id="create_current_application_file_operation",
)
async def create_current_application_file_operation(
    request: Request,
    body: FileOperationCreate,
    application_code: str = Query(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> FileOperationRuntime:
    await _application_api_context(request, application_code)
    return await create_file_operation(
        request, body, await _implicit_space_id(request), idempotency_key
    )


@router.post(
    "/applications/{application_id}/direct_uploads",
    status_code=201,
    response_model=DirectUploadSessionRuntime,
    operation_id="create_application_direct_upload",
)
async def create_application_direct_upload(
    request: Request,
    application_id: UUID,
    body: DirectUploadCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DirectUploadSessionRuntime:
    return await create_direct_upload(
        request,
        body,
        await _implicit_space_id(request, application_id),
        idempotency_key,
    )


@router.post(
    "/application/direct_uploads",
    status_code=201,
    response_model=DirectUploadSessionRuntime,
    operation_id="create_current_application_direct_upload",
)
async def create_current_application_direct_upload(
    request: Request,
    body: DirectUploadCreate,
    application_code: str = Query(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> DirectUploadSessionRuntime:
    await _application_api_context(request, application_code)
    return await create_direct_upload(
        request, body, await _implicit_space_id(request), idempotency_key
    )


@router.post(
    "/applications/{application_id}/presigned_downloads",
    status_code=201,
    operation_id="create_application_presigned_download",
)
async def create_application_presigned_download(
    request: Request, application_id: UUID, body: PresignedDownloadCreate
) -> Any:
    return await create_presigned_download(
        request, body, await _implicit_space_id(request, application_id)
    )


@router.post(
    "/application/presigned_downloads",
    status_code=201,
    operation_id="create_current_application_presigned_download",
)
async def create_current_application_presigned_download(
    request: Request, body: PresignedDownloadCreate, application_code: str = Query(min_length=1)
) -> Any:
    await _application_api_context(request, application_code)
    return await create_presigned_download(request, body, await _implicit_space_id(request))


@router.post(
    "/applications/{application_id}/multipart_uploads",
    status_code=201,
    response_model=MultipartUploadRuntime,
    operation_id="create_application_multipart_upload",
)
async def create_application_multipart_upload(
    request: Request,
    application_id: UUID,
    body: MultipartCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MultipartUploadRuntime:
    return await create_multipart_upload(
        request,
        body,
        await _implicit_space_id(request, application_id),
        idempotency_key,
    )


@router.post(
    "/application/multipart_uploads",
    status_code=201,
    response_model=MultipartUploadRuntime,
    operation_id="create_current_application_multipart_upload",
)
async def create_current_application_multipart_upload(
    request: Request,
    body: MultipartCreate,
    application_code: str = Query(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> MultipartUploadRuntime:
    await _application_api_context(request, application_code)
    return await create_multipart_upload(
        request, body, await _implicit_space_id(request), idempotency_key
    )
