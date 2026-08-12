"""Identity context endpoints."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Context"])


class PrincipalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    display_name: str


class TenantSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    membership_status: str


class MeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal: PrincipalSummary
    current_tenant: TenantSummary
    available_tenants: list[TenantSummary]
    coarse_permissions: list[str]
    authorization_version: int


class MembershipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=200)


class MembershipUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    reason: str = Field(min_length=1, max_length=500)


def _context(request: Request) -> PrincipalContext:
    context = getattr(request.state, "principal_context", None)
    if not isinstance(context, PrincipalContext):
        raise ApiError("authentication_required", "Authentication required", status_code=401)
    return context


@router.get("/me", response_model=MeResponse, operation_id="get_me")
async def get_me(request: Request) -> Any:
    context = getattr(request.state, "principal_context", None)
    if not isinstance(context, PrincipalContext):
        raise ApiError("authentication_required", "Authentication required", status_code=401)
    provider = getattr(request.app.state, "identity_context_provider", None)
    if provider is None:
        raise ApiError("internal_error", "Identity context is not configured", status_code=500)
    return await provider.get_me(context)


def _management_service(request: Request) -> Any:
    service = getattr(request.app.state, "identity_management", None)
    if service is None:
        raise ApiError("internal_error", "Identity management is not configured", status_code=500)
    return service


@router.get("/users", operation_id="list_users")
async def list_users(request: Request) -> Any:
    return await _management_service(request).list_users(_context(request))


@router.get("/users/{user_id}", operation_id="get_user")
async def get_user(request: Request, user_id: str) -> Any:
    return await _management_service(request).get_user(_context(request), user_id)


@router.get("/members", operation_id="list_members")
async def list_members(request: Request) -> Any:
    return await _management_service(request).list_members(_context(request))


@router.post("/members", status_code=201, operation_id="create_member")
async def create_member(request: Request, body: MembershipCreate) -> Any:
    return await _management_service(request).create_member(_context(request), body)


@router.get("/members/{membership_id}", operation_id="get_member")
async def get_member(request: Request, membership_id: str) -> Any:
    return await _management_service(request).get_member(_context(request), membership_id)


@router.patch("/members/{membership_id}", operation_id="update_member")
async def update_member(request: Request, body: MembershipUpdate, membership_id: str) -> Any:
    return await _management_service(request).update_member(_context(request), membership_id, body)


# ── Group membership ──────────────────────────────────────────────────────────


@router.get("/groups/{group_id}/members", operation_id="list_group_members")
async def list_group_members(request: Request, group_id: str) -> Any:
    return await _management_service(request).list_group_members(_context(request), group_id)


class AddGroupMemberBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    membership_id: str


@router.post("/groups/{group_id}/members", status_code=204, operation_id="add_group_member")
async def add_group_member(request: Request, group_id: str, body: AddGroupMemberBody) -> None:
    await _management_service(request).add_group_member(_context(request), group_id, body.membership_id)


@router.delete(
    "/groups/{group_id}/members/{membership_id}", status_code=204, operation_id="remove_group_member"
)
async def remove_group_member(request: Request, group_id: str, membership_id: str) -> None:
    await _management_service(request).remove_group_member(_context(request), group_id, membership_id)
