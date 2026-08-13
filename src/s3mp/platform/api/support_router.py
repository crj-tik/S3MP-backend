"""Explicit support access routes; every mutation is platform-authorized and CSRF-protected."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.dependencies import application_service
from s3mp.platform.api.dependencies import platform_permission
from s3mp.platform.application.support_access import SupportAccessService
from s3mp.platform.domain.context import PlatformContext

router = APIRouter(prefix="/api/v1/platform/support-access", tags=["Platform support"])
support_service = application_service("platform_support_access")


class SupportAccessCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    reason: str = Field(min_length=1, max_length=500)
    expires_at: datetime


ManageContext = Annotated[PlatformContext, platform_permission("platform.support.manage")]


@router.post("", status_code=201, operation_id="request_support_access")
async def request_access(
    body: SupportAccessCreate,
    context: ManageContext,
    service: Annotated[SupportAccessService, support_service],
) -> object:
    return await service.request(
        context, tenant_id=body.tenant_id, reason=body.reason, expires_at=body.expires_at
    )


@router.post("/{request_id}/approvals", operation_id="approve_support_access")
async def approve_access(
    request_id: UUID,
    context: ManageContext,
    service: Annotated[SupportAccessService, support_service],
) -> object:
    return await service.approve(context, request_id)


@router.delete("/{request_id}", status_code=204, operation_id="revoke_support_access")
async def revoke_access(
    request_id: UUID,
    context: ManageContext,
    service: Annotated[SupportAccessService, support_service],
) -> None:
    await service.revoke(context, request_id)
