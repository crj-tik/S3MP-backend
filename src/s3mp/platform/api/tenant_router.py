"""Platform-only tenant lifecycle HTTP routes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.cursor import CursorCodec
from s3mp.common.api.dependencies import application_service
from s3mp.common.errors import ApiError
from s3mp.platform.api.dependencies import platform_permission
from s3mp.platform.application.tenant_lifecycle import PlatformTenantLifecycleService
from s3mp.platform.domain.context import PlatformContext

router = APIRouter(prefix="/api/v1/platform", tags=["Platform tenants"])
tenant_service = application_service("platform_tenant_lifecycle")
_codec = CursorCodec(b"s3mp-management-cursor-key-v1")
_platform_tenant = UUID(int=0)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TenantCreate(_Strict):
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=200)
    initial_admin_user_id: UUID


class TenantUpdate(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "suspended"] | None = None


class PlatformTenantResponse(_Strict):
    id: UUID
    slug: str
    name: str
    status: Literal["active", "suspended"]
    created_at: datetime | None = None


class PlatformTenantPage(_Strict):
    items: list[PlatformTenantResponse]
    next_cursor: str | None = None


ManageContext = Annotated[PlatformContext, platform_permission("platform.tenants.manage")]
ReadContext = Annotated[PlatformContext, platform_permission("platform.tenants.read")]


def _cursor(value: str | None, context: PlatformContext) -> UUID | None:
    if value is None:
        return None
    position = _codec.decode(value, _platform_tenant, context.user_id, 1, query="platform_tenants")
    try:
        return UUID(position)
    except ValueError as exc:
        raise ApiError("invalid_cursor", "Invalid platform cursor", 400) from exc


def _next(position: UUID | None, context: PlatformContext) -> str | None:
    return (
        _codec.encode(_platform_tenant, context.user_id, 1, str(position), query="platform_tenants")
        if position
        else None
    )


@router.get(
    "/tenants",
    response_model=PlatformTenantPage,
    operation_id="list_platform_tenants",
)
async def list_tenants(
    context: ReadContext,
    service: Annotated[PlatformTenantLifecycleService, tenant_service],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> PlatformTenantPage:
    items, position = await service.list_tenants(
        context, limit=limit, cursor=_cursor(cursor, context)
    )
    return PlatformTenantPage(
        items=[PlatformTenantResponse.model_validate(item) for item in items],
        next_cursor=_next(position, context),
    )


@router.get(
    "/tenants/{tenant_id}",
    response_model=PlatformTenantResponse,
    operation_id="get_platform_tenant",
)
async def get_tenant(
    tenant_id: UUID,
    context: ReadContext,
    service: Annotated[PlatformTenantLifecycleService, tenant_service],
) -> PlatformTenantResponse:
    return PlatformTenantResponse.model_validate(await service.get_tenant(context, tenant_id))


@router.post(
    "/tenants",
    status_code=201,
    response_model=PlatformTenantResponse,
    operation_id="create_platform_tenant",
)
async def create_tenant(
    body: TenantCreate,
    context: ManageContext,
    service: Annotated[PlatformTenantLifecycleService, tenant_service],
) -> PlatformTenantResponse:
    return PlatformTenantResponse.model_validate(await service.create_tenant(
        context, slug=body.slug, name=body.name, initial_admin_user_id=body.initial_admin_user_id
    ))


@router.patch(
    "/tenants/{tenant_id}",
    response_model=PlatformTenantResponse,
    operation_id="update_platform_tenant",
)
async def update_tenant(
    tenant_id: UUID,
    body: TenantUpdate,
    context: ManageContext,
    service: Annotated[PlatformTenantLifecycleService, tenant_service],
) -> PlatformTenantResponse:
    result = await service.update_tenant(
        context, tenant_id, name=body.name, status=body.status
    )
    return PlatformTenantResponse.model_validate(result)
