"""Platform-only tenant lifecycle HTTP routes."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.dependencies import application_service
from s3mp.platform.api.dependencies import platform_permission
from s3mp.platform.application.tenant_lifecycle import PlatformTenantLifecycleService
from s3mp.platform.domain.context import PlatformContext

router = APIRouter(prefix="/api/v1/platform", tags=["Platform tenants"])
tenant_service = application_service("platform_tenant_lifecycle")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TenantCreate(_Strict):
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=200)
    initial_admin_user_id: UUID


class TenantUpdate(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "suspended"] | None = None


ManageContext = Annotated[PlatformContext, platform_permission("platform.tenants.manage")]
ReadContext = Annotated[PlatformContext, platform_permission("platform.tenants.read")]


@router.get("/tenants", operation_id="list_platform_tenants")
async def list_tenants(
    context: ReadContext,
    service: Annotated[PlatformTenantLifecycleService, tenant_service],
) -> object:
    return {"items": await service.list_tenants(context)}


@router.get("/tenants/{tenant_id}", operation_id="get_platform_tenant")
async def get_tenant(
    tenant_id: UUID,
    context: ReadContext,
    service: Annotated[PlatformTenantLifecycleService, tenant_service],
) -> object:
    return await service.get_tenant(context, tenant_id)


@router.post("/tenants", status_code=201, operation_id="create_platform_tenant")
async def create_tenant(
    body: TenantCreate,
    context: ManageContext,
    service: Annotated[PlatformTenantLifecycleService, tenant_service],
) -> object:
    return await service.create_tenant(
        context, slug=body.slug, name=body.name, initial_admin_user_id=body.initial_admin_user_id
    )


@router.patch("/tenants/{tenant_id}", operation_id="update_platform_tenant")
async def update_tenant(
    tenant_id: UUID,
    body: TenantUpdate,
    context: ManageContext,
    service: Annotated[PlatformTenantLifecycleService, tenant_service],
) -> object:
    return await service.update_tenant(context, tenant_id, name=body.name, status=body.status)
