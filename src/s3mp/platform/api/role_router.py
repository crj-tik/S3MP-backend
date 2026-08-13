"""Global platform-role grant and revocation routes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.dependencies import application_service
from s3mp.platform.api.dependencies import platform_permission
from s3mp.platform.application.role_management import PlatformRoleManagementService
from s3mp.platform.domain.context import PlatformContext

router = APIRouter(prefix="/api/v1/platform", tags=["Platform roles"])
role_service = application_service("platform_role_management")


class PlatformRoleGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    role_name: str = Field(min_length=1, max_length=120)
    expires_at: datetime | None = None


ManageContext = Annotated[PlatformContext, platform_permission("platform.roles.manage")]


@router.post("/role-bindings", status_code=201, operation_id="grant_platform_role")
async def grant_role(
    body: PlatformRoleGrant,
    context: ManageContext,
    service: Annotated[PlatformRoleManagementService, role_service],
) -> object:
    return await service.grant(
        context, user_id=body.user_id, role_name=body.role_name, expires_at=body.expires_at
    )


@router.delete("/role-bindings/{binding_id}", status_code=204, operation_id="revoke_platform_role")
async def revoke_role(
    binding_id: UUID,
    context: ManageContext,
    service: Annotated[PlatformRoleManagementService, role_service],
) -> None:
    await service.revoke(context, binding_id)
