"""Storage connections and spaces HTTP endpoints."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.cursor import CursorCodec
from s3mp.common.api.dependencies import management_permission
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext
from s3mp.storage.infrastructure.models import StorageConnectionStatus

router = APIRouter(prefix="/api/v1", tags=["Storage"])


# ── DTOs ──────────────────────────────────────────────────────────────────────


class ProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    write_test_prefix: str | None = Field(default=None, max_length=1024)


class ProbeResult(BaseModel):
    status: str
    readable: bool
    writable: bool
    checked_at: datetime
    failure_reason: str | None = None


class StorageConnectionResponse(BaseModel):
    """租户可见的对象存储连接，不暴露凭据引用或密钥材料。"""

    id: UUID
    tenant_id: UUID | None = None
    name: str
    endpoint: str | None = None
    region: str | None = None
    path_style: bool | None = None
    signature_version: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StorageConnectionPage(BaseModel):
    items: list[StorageConnectionResponse]
    next_cursor: str | None = None


def _page(
    items: list[dict[str, Any]], position: str | None, context: PrincipalContext, *, query: str
) -> dict[str, Any]:
    return {
        "items": items,
        "next_cursor": CursorCodec(b"s3mp-management-cursor-key-v1").encode(
            context.tenant_id,
            context.principal_id,
            context.authorization_version,
            position,
            query=query,
        )
        if position
        else None,
    }


def _cursor(value: str | None, context: PrincipalContext, *, query: str) -> str | None:
    if value is None:
        return None
    return CursorCodec(b"s3mp-management-cursor-key-v1").decode(
        value,
        context.tenant_id,
        context.principal_id,
        context.authorization_version,
        query=query,
    )


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


@router.get(
    "/storage_connections",
    response_model=StorageConnectionPage,
    operation_id="list_storage_connections",
)
async def list_storage_connections(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("list_storage_connections")],
    cursor: str | None = Query(default=None),
    status: Annotated[StorageConnectionStatus, Query()] = StorageConnectionStatus.ACTIVE,
) -> StorageConnectionPage:
    query = f"storage_connections:{status.value}"
    items, position = await _svc(request).list_connections(
        context, cursor=_cursor(cursor, context, query=query), status=status
    )
    return StorageConnectionPage.model_validate(
        _page(items, position, context, query=query)
    )


@router.get(
    "/storage_connections/{connection_id}",
    response_model=StorageConnectionResponse,
    operation_id="get_storage_connection",
)
async def get_storage_connection(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("get_storage_connection")],
    connection_id: str = Path(min_length=1),
) -> StorageConnectionResponse:
    return StorageConnectionResponse.model_validate(
        await _svc(request).get_connection(context, connection_id)
    )


@router.post(
    "/storage_connections/{connection_id}/probes",
    response_model=ProbeResult,
    operation_id="probe_storage_connection",
)
async def probe_storage_connection(
    request: Request,
    body: ProbeRequest,
    context: Annotated[PrincipalContext, management_permission("probe_storage_connection")],
    connection_id: str = Path(min_length=1),
) -> ProbeResult:
    result = await _svc(request).probe_connection(context, connection_id, body.write_test_prefix)
    return ProbeResult.model_validate(result)
