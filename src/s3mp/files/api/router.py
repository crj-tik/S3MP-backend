"""Files, uploads, presigned downloads, and multipart HTTP endpoints."""

from typing import Any

from fastapi import APIRouter, Body, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.application.idempotency import IdempotencyGuard
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Files", "Uploads", "Multipart"])


# ── DTOs ──────────────────────────────────────────────────────────────────────


class FileOperationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_type: str = Field(min_length=1, max_length=32)
    source_key: str | None = Field(default=None, max_length=1024)
    destination_key: str | None = Field(default=None, max_length=1024)
    keys: list[str] | None = Field(default=None)


class UploadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_key: str = Field(min_length=1, max_length=1024)
    content_length: int = Field(ge=0)
    content_type: str = Field(min_length=1, max_length=255)
    checksum: str | None = Field(default=None, max_length=512)
    direct_requested: bool = False


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


class MultipartPartCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_number: int = Field(ge=1, le=10000)


class MultipartPartConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    etag: str = Field(min_length=1, max_length=512)
    content_length: int = Field(ge=0)


class MultipartCompletePart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    part_number: int = Field(ge=1, le=10000)
    etag: str = Field(min_length=1, max_length=512)


class MultipartComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parts: list[MultipartCompletePart] = Field(min_length=1)


# ── Dependencies ──────────────────────────────────────────────────────────────


def _context(request: Request) -> PrincipalContext:
    context = getattr(request.state, "principal_context", None)
    if not isinstance(context, PrincipalContext):
        raise ApiError("authentication_required", "Authentication required", status_code=401)
    return context


def _file_svc(request: Request) -> Any:
    svc = getattr(request.app.state, "file_service", None)
    if svc is None:
        raise ApiError("internal_error", "File service is not configured", status_code=500)
    return svc


def _idempotency_key(value: str | None) -> str:
    return IdempotencyGuard.validate_key(value)


# ── Files ─────────────────────────────────────────────────────────────────────


@router.get("/storage_spaces/{space_id}/files", operation_id="list_files")
async def list_files(
    request: Request,
    space_id: str = Path(min_length=1),
    prefix: str | None = None,
) -> Any:
    return await _file_svc(request).list_files(_context(request), space_id, prefix or "")


@router.get("/storage_spaces/{space_id}/files/{file_id}", operation_id="get_file")
async def get_file(
    request: Request,
    space_id: str = Path(min_length=1),
    file_id: str = Path(min_length=1),
) -> Any:
    return await _file_svc(request).get_file(_context(request), space_id, file_id)


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
    operation_id="create_file_operation",
)
async def create_file_operation(
    request: Request,
    body: FileOperationCreate,
    space_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _file_svc(request).create_file_operation(
        _context(request), space_id, body, idempotency_key=_idempotency_key(idempotency_key)
    )


@router.get("/file_operations/{operation_id}", operation_id="get_file_operation")
async def get_file_operation(
    request: Request,
    operation_id: str = Path(min_length=1),
) -> Any:
    return await _file_svc(request).get_file_operation(_context(request), operation_id)


# ── Uploads ───────────────────────────────────────────────────────────────────


@router.post("/storage_spaces/{space_id}/uploads", status_code=201, operation_id="create_upload")
async def create_upload(
    request: Request,
    body: UploadCreate,
    space_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _file_svc(request).create_upload(
        _context(request), space_id, body, idempotency_key=_idempotency_key(idempotency_key)
    )


@router.get("/uploads/{upload_id}", operation_id="get_upload")
async def get_upload(
    request: Request,
    upload_id: str = Path(min_length=1),
) -> Any:
    return await _file_svc(request).get_upload(_context(request), upload_id)


@router.put("/uploads/{upload_id}/content", status_code=204, operation_id="proxy_upload_content")
async def proxy_upload_content(
    request: Request,
    upload_id: str = Path(min_length=1),
    content_length: int = Header(alias="Content-Length"),
    content_type: str = Header(alias="Content-Type"),
    body: bytes = Body(..., media_type="application/octet-stream"),
) -> None:
    await _file_svc(request).proxy_upload_content(
        _context(request), upload_id, body, content_length, content_type
    )


@router.post("/uploads/{upload_id}/completion", operation_id="complete_upload")
async def complete_upload(
    request: Request,
    body: UploadComplete,
    upload_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _file_svc(request).complete_upload(
        _context(request), upload_id, body, idempotency_key=_idempotency_key(idempotency_key)
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
    operation_id="create_multipart_upload",
)
async def create_multipart_upload(
    request: Request,
    body: MultipartCreate,
    space_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _file_svc(request).create_multipart_upload(
        _context(request), space_id, body, idempotency_key=_idempotency_key(idempotency_key)
    )


@router.get("/multipart_uploads/{multipart_id}", operation_id="get_multipart_upload")
async def get_multipart_upload(
    request: Request,
    multipart_id: str = Path(min_length=1),
) -> Any:
    return await _file_svc(request).get_multipart_upload(_context(request), multipart_id)


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


@router.get("/multipart_uploads/{multipart_id}/parts", operation_id="list_multipart_parts")
async def list_multipart_parts(
    request: Request,
    multipart_id: str = Path(min_length=1),
) -> Any:
    return await _file_svc(request).list_multipart_parts(_context(request), multipart_id)


@router.post(
    "/multipart_uploads/{multipart_id}/parts", status_code=201, operation_id="create_multipart_part"
)
async def create_multipart_part(
    request: Request,
    body: MultipartPartCreate,
    multipart_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _file_svc(request).create_multipart_part(
        _context(request), multipart_id, body, idempotency_key=_idempotency_key(idempotency_key)
    )


@router.put(
    "/multipart_uploads/{multipart_id}/parts/{part_number}", operation_id="confirm_multipart_part"
)
async def confirm_multipart_part(
    request: Request,
    body: MultipartPartConfirm,
    multipart_id: str = Path(min_length=1),
    part_number: int = Path(ge=1, le=10000),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _file_svc(request).confirm_multipart_part(
        _context(request),
        multipart_id,
        part_number,
        body,
        idempotency_key=_idempotency_key(idempotency_key),
    )


@router.post(
    "/multipart_uploads/{multipart_id}/completion", operation_id="complete_multipart_upload"
)
async def complete_multipart_upload(
    request: Request,
    body: MultipartComplete,
    multipart_id: str = Path(min_length=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Any:
    return await _file_svc(request).complete_multipart_upload(
        _context(request), multipart_id, body, idempotency_key=_idempotency_key(idempotency_key)
    )
