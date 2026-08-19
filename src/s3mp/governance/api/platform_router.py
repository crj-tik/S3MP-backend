"""Platform-level quota allocation endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.cursor import CursorCodec
from s3mp.common.api.dependencies import application_service
from s3mp.governance.api.router import QuotaResponse
from s3mp.governance.application.governance_service import PlatformQuotaService
from s3mp.governance.domain.quota import QuotaAllocationMode, QuotaLifecycleStatus
from s3mp.platform.api.dependencies import platform_permission
from s3mp.platform.domain.context import PlatformContext

router = APIRouter(prefix="/api/v1/platform", tags=["Platform quotas"])
quota_service = application_service("platform_quota_service")
_codec = CursorCodec(b"s3mp-management-cursor-key-v1")
_scope = UUID(int=0)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformQuotaCreate(_Strict):
    tenant_id: UUID
    application_id: UUID | None = None
    limit_gib: int = Field(ge=0)


class PlatformQuotaUpdate(_Strict):
    limit_gib: int = Field(ge=0)


class PlatformQuotaPage(_Strict):
    items: list[QuotaResponse]
    next_cursor: str | None = None


def _cursor(value: str | None, context: PlatformContext, query: str) -> UUID | None:
    if value is None:
        return None
    return UUID(_codec.decode(value, _scope, context.user_id, 1, query=query))


def _next(value: UUID | None, context: PlatformContext, query: str) -> str | None:
    return _codec.encode(_scope, context.user_id, 1, str(value), query=query) if value else None


ReadContext = Annotated[
    PlatformContext, platform_permission("platform.quotas.read", "list_platform_quotas")
]
ManageContext = Annotated[
    PlatformContext, platform_permission("platform.quotas.manage", "create_platform_quota")
]
UpdateContext = Annotated[
    PlatformContext, platform_permission("platform.quotas.manage", "update_platform_quota")
]
RevokeContext = Annotated[
    PlatformContext, platform_permission("platform.quotas.manage", "revoke_platform_quota")
]


@router.get("/quotas", response_model=PlatformQuotaPage, operation_id="list_platform_quotas")
async def list_platform_quotas(
    context: ReadContext,
    service: Annotated[PlatformQuotaService, quota_service],
    tenant_id: UUID | None = None,
    application_id: UUID | None = None,
    status: Annotated[QuotaLifecycleStatus | None, Query()] = QuotaLifecycleStatus.ACTIVE,
    allocation_mode: Annotated[QuotaAllocationMode | None, Query()] = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> PlatformQuotaPage:
    query = f"platform_quotas:{tenant_id}:{application_id}:{status}:{allocation_mode}"
    items, position = await service.list_quotas(
        context,
        tenant_id=tenant_id,
        application_id=application_id,
        status=status,
        allocation_mode=allocation_mode,
        limit=limit,
        cursor=_cursor(cursor, context, query),
    )
    return PlatformQuotaPage(
        items=[QuotaResponse.model_validate(i) for i in items],
        next_cursor=_next(position, context, query),
    )


@router.post(
    "/quotas", status_code=201, response_model=QuotaResponse, operation_id="create_platform_quota"
)
async def create_platform_quota(
    body: Annotated[PlatformQuotaCreate, Body()],
    context: ManageContext,
    service: Annotated[PlatformQuotaService, quota_service],
) -> QuotaResponse:
    return QuotaResponse.model_validate(
        await service.create_quota(
            context,
            tenant_id=body.tenant_id,
            application_id=body.application_id,
            limit_gib=body.limit_gib,
        )
    )


@router.patch(
    "/quotas/{quota_id}", response_model=QuotaResponse, operation_id="update_platform_quota"
)
async def update_platform_quota(
    quota_id: UUID,
    body: Annotated[PlatformQuotaUpdate, Body()],
    context: UpdateContext,
    service: Annotated[PlatformQuotaService, quota_service],
) -> QuotaResponse:
    return QuotaResponse.model_validate(
        await service.update_quota(context, quota_id, body.limit_gib)
    )


@router.delete(
    "/quotas/{quota_id}", response_model=QuotaResponse, operation_id="revoke_platform_quota"
)
async def revoke_platform_quota(
    quota_id: UUID,
    context: RevokeContext,
    service: Annotated[PlatformQuotaService, quota_service],
) -> QuotaResponse:
    return QuotaResponse.model_validate(await service.revoke_quota(context, quota_id))
