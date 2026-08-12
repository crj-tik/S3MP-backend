"""Strict HTTP boundary for identity and membership management."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.cursor import CursorCodec
from s3mp.common.api.dependencies import (
    application_service,
    management_permission,
    principal_context,
)
from s3mp.common.api.etag import check_etag, require_if_match
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Context"])
identity_service = application_service("identity_management")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrincipalSummary(_Strict):
    id: str
    type: Literal["user", "group", "application"]
    display_name: str


class TenantSummary(_Strict):
    id: str
    name: str
    membership_status: Literal["invited", "active", "suspended", "removed"]


class MeResponse(_Strict):
    principal: PrincipalSummary
    current_tenant: TenantSummary
    available_tenants: list[TenantSummary]
    coarse_permissions: list[str] = Field(json_schema_extra={"uniqueItems": True})
    authorization_version: int = Field(ge=1)


class UserResponse(_Strict):
    id: str
    email: str = Field(json_schema_extra={"format": "email"})
    display_name: str
    status: Literal["active", "disabled"]
    created_at: datetime


class MembershipResponse(_Strict):
    id: str
    user: UserResponse
    principal: PrincipalSummary
    status: Literal["invited", "active", "suspended", "removed"]
    authorization_version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    etag: str


class UserPage(_Strict):
    items: list[UserResponse]
    next_cursor: str | None


class MembershipPage(_Strict):
    items: list[MembershipResponse]
    next_cursor: str | None


class MembershipCreate(_Strict):
    email: str = Field(min_length=3, max_length=320, json_schema_extra={"format": "email"})
    display_name: str | None = Field(default=None, max_length=200)


class MembershipUpdate(_Strict):
    status: Literal["invited", "active", "suspended", "removed"]
    reason: str = Field(min_length=1, max_length=500)


class AddGroupMemberBody(_Strict):
    membership_id: UUID


Context = Annotated[PrincipalContext, Depends(principal_context)]


def _cursor(value: str | None, context: PrincipalContext) -> UUID | None:
    if value is None:
        return None
    position = CursorCodec(b"s3mp-management-cursor-key-v1").decode(
        value, context.tenant_id, context.principal_id, context.authorization_version
    )
    return UUID(position)


def _page(
    items: list[dict[str, object]], position: UUID | None, context: PrincipalContext
) -> dict[str, object]:
    return {
        "items": items,
        "next_cursor": CursorCodec(b"s3mp-management-cursor-key-v1").encode(
            context.tenant_id, context.principal_id, context.authorization_version, str(position)
        )
        if position
        else None,
    }


@router.get("/me", response_model=MeResponse, operation_id="get_me")
async def get_me(context: Context, service: Annotated[object, identity_service]) -> object:
    return await service.get_me(context)  # type: ignore[union-attr]


@router.get("/users", response_model=UserPage, operation_id="list_users")
async def list_users(
    context: Annotated[PrincipalContext, management_permission("list_users")],
    service: Annotated[object, identity_service],
    cursor: str | None = Query(default=None),
) -> object:
    items, next_position = await service.list_users(context, cursor=_cursor(cursor, context))  # type: ignore[union-attr]
    return _page(items, next_position, context)


@router.get("/users/{user_id}", response_model=UserResponse, operation_id="get_user")
async def get_user(
    user_id: UUID,
    context: Annotated[PrincipalContext, management_permission("get_user")],
    service: Annotated[object, identity_service],
) -> object:
    return await service.get_user(context, user_id)  # type: ignore[union-attr]


@router.get("/members", response_model=MembershipPage, operation_id="list_members")
async def list_members(
    context: Annotated[PrincipalContext, management_permission("list_members")],
    service: Annotated[object, identity_service],
    cursor: str | None = Query(default=None),
) -> object:
    items, next_position = await service.list_members(context, cursor=_cursor(cursor, context))  # type: ignore[union-attr]
    return _page(items, next_position, context)


@router.post(
    "/members", response_model=MembershipResponse, status_code=201, operation_id="create_member"
)
async def create_member(
    body: MembershipCreate,
    context: Annotated[PrincipalContext, management_permission("create_member")],
    service: Annotated[object, identity_service],
    response: Response,
) -> object:
    result = await service.create_member(context, body)  # type: ignore[union-attr]
    response.headers["Location"] = f"/api/v1/members/{result['id']}"
    return result


@router.get(
    "/members/{membership_id}", response_model=MembershipResponse, operation_id="get_member"
)
async def get_member(
    membership_id: UUID,
    context: Annotated[PrincipalContext, management_permission("get_member")],
    service: Annotated[object, identity_service],
) -> object:
    return await service.get_member(context, membership_id)  # type: ignore[union-attr]


@router.patch(
    "/members/{membership_id}", response_model=MembershipResponse, operation_id="update_member"
)
async def update_member(
    membership_id: UUID,
    body: MembershipUpdate,
    context: Annotated[PrincipalContext, management_permission("update_member")],
    service: Annotated[object, identity_service],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> object:
    current = await service.get_member(context, membership_id)  # type: ignore[union-attr]
    check_etag(current["etag"], require_if_match(if_match))
    return await service.update_member(context, membership_id, body)  # type: ignore[union-attr]


@router.get(
    "/groups/{group_id}/members", response_model=MembershipPage, operation_id="list_group_members"
)
async def list_group_members(
    group_id: UUID,
    context: Annotated[PrincipalContext, management_permission("list_group_members")],
    service: Annotated[object, identity_service],
    cursor: str | None = Query(default=None),
) -> object:
    items, next_position = await service.list_group_members(
        context, group_id, cursor=_cursor(cursor, context)
    )  # type: ignore[union-attr]
    return _page(items, next_position, context)


@router.post("/groups/{group_id}/members", status_code=204, operation_id="add_group_member")
async def add_group_member(
    group_id: UUID,
    body: AddGroupMemberBody,
    context: Annotated[PrincipalContext, management_permission("add_group_member")],
    service: Annotated[object, identity_service],
) -> None:
    await service.add_group_member(context, group_id, body.membership_id)  # type: ignore[union-attr]


@router.delete(
    "/groups/{group_id}/members/{membership_id}",
    status_code=204,
    operation_id="remove_group_member",
)
async def remove_group_member(
    group_id: UUID,
    membership_id: UUID,
    context: Annotated[PrincipalContext, management_permission("remove_group_member")],
    service: Annotated[object, identity_service],
) -> None:
    await service.remove_group_member(context, group_id, membership_id)  # type: ignore[union-attr]
