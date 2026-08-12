"""Storage connections and spaces HTTP endpoints."""

from typing import Any

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Storage"])


# ── DTOs ──────────────────────────────────────────────────────────────────────


class StorageConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    endpoint: str = Field(min_length=1, max_length=500)
    region: str = Field(min_length=1, max_length=100)
    path_style: bool = True
    credential_reference: str = Field(min_length=1, max_length=500)


class StorageSpaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    connection_id: str
    bucket: str = Field(min_length=1, max_length=255)
    root_prefix: str = Field(default="", max_length=1024)


class ProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    write_test_prefix: str | None = Field(default=None, max_length=1024)


# ── Dependencies ──────────────────────────────────────────────────────────────


def _context(request: Request) -> PrincipalContext:
    context = getattr(request.state, "principal_context", None)
    if not isinstance(context, PrincipalContext):
        raise ApiError("authentication_required", "Authentication required", status_code=401)
    return context


def _svc(request: Request) -> Any:
    svc = getattr(request.app.state, "storage_service", None)
    if svc is None:
        raise ApiError("internal_error", "Storage service is not configured", status_code=500)
    return svc


# ── Connections ───────────────────────────────────────────────────────────────


@router.get("/storage_connections", operation_id="list_storage_connections")
async def list_storage_connections(request: Request) -> Any:
    return await _svc(request).list_connections(_context(request).tenant_id)


@router.post("/storage_connections", status_code=201, operation_id="create_storage_connection")
async def create_storage_connection(
    request: Request,
    body: StorageConnectionCreate,
) -> Any:
    return await _svc(request).create_connection(_context(request).tenant_id, body)


@router.get("/storage_connections/{connection_id}", operation_id="get_storage_connection")
async def get_storage_connection(
    request: Request,
    connection_id: str = Path(min_length=1),
) -> Any:
    return await _svc(request).get_connection(_context(request).tenant_id, connection_id)


@router.post("/storage_connections/{connection_id}/probes", operation_id="probe_storage_connection")
async def probe_storage_connection(
    request: Request,
    body: ProbeRequest,
    connection_id: str = Path(min_length=1),
) -> Any:
    return await _svc(request).probe_connection(
        _context(request).tenant_id, connection_id, body.write_test_prefix
    )


# ── Spaces ────────────────────────────────────────────────────────────────────


@router.get("/storage_spaces", operation_id="list_storage_spaces")
async def list_storage_spaces(request: Request) -> Any:
    return await _svc(request).list_spaces(_context(request).tenant_id)


@router.post("/storage_spaces", status_code=201, operation_id="create_storage_space")
async def create_storage_space(request: Request, body: StorageSpaceCreate) -> Any:
    return await _svc(request).create_space(_context(request).tenant_id, body)


@router.get("/storage_spaces/{space_id}", operation_id="get_storage_space")
async def get_storage_space(
    request: Request,
    space_id: str = Path(min_length=1),
) -> Any:
    return await _svc(request).get_space(_context(request).tenant_id, space_id)
