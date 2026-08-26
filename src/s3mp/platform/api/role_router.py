"""Global platform-role grant and revocation routes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from s3mp.common.api.dependencies import application_service
from s3mp.platform.api.dependencies import platform_permission
from s3mp.platform.application.role_management import PlatformRoleManagementService
from s3mp.platform.domain.context import PlatformContext

router = APIRouter(prefix="/api/v1/platform", tags=["Platform roles"])
role_service = application_service("platform_role_management")


class PlatformRoleGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    role_names: list[
        Literal["platform_admin", "platform_operator", "platform_auditor", "tenant-admin"]
    ] = Field(min_length=1, max_length=4)
    expires_at: datetime | None = None

    @field_validator("role_names")
    @classmethod
    def role_names_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("role_names must not contain duplicates")
        return value


class PlatformRoleAssignmentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_names: list[
        Literal["platform_admin", "platform_operator", "platform_auditor", "tenant-admin"]
    ] = Field(min_length=1, max_length=4)
    expires_at: datetime | None = None

    @field_validator("role_names")
    @classmethod
    def role_names_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("role_names must not contain duplicates")
        return value


ManageContext = Annotated[PlatformContext, platform_permission("platform.roles.manage")]


@router.post("/role-bindings", status_code=200, operation_id="grant_platform_role")
async def grant_role(
    body: PlatformRoleGrant,
    context: ManageContext,
    service: Annotated[PlatformRoleManagementService, role_service],
) -> object:
    return await service.assign(
        context, user_id=body.user_id, role_names=body.role_names, expires_at=body.expires_at
    )


@router.put("/role-bindings/{user_id}", operation_id="update_platform_role_assignment")
async def update_assignment(
    user_id: UUID,
    body: PlatformRoleAssignmentUpdate,
    context: ManageContext,
    service: Annotated[PlatformRoleManagementService, role_service],
) -> object:
    return await service.assign(
        context, user_id=user_id, role_names=body.role_names, expires_at=body.expires_at
    )


@router.delete("/role-bindings/{user_id}", status_code=204, operation_id="revoke_platform_role")
async def revoke_role(
    user_id: UUID,
    context: ManageContext,
    service: Annotated[PlatformRoleManagementService, role_service],
) -> None:
    await service.revoke(context, user_id)
