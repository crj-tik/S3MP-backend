"""Strict HTTP boundary for tenant authorization management."""

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

import yaml
from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, ConfigDict, Field

from s3mp.authorization.application.management_service import AuthorizationManagementService
from s3mp.common.api.cursor import CursorCodec
from s3mp.common.api.dependencies import application_service, management_permission
from s3mp.common.api.etag import check_etag, require_if_match
from s3mp.identity.api.router import PrincipalSummary
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Authorization"])
authorization_service = application_service("authorization_management")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GroupWrite(_Strict):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class GroupResponse(_Strict):
    id: str
    principal: PrincipalSummary
    name: str
    description: str
    member_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    etag: str


class GroupPage(_Strict):
    items: list[GroupResponse]
    next_cursor: str | None


class RoleWrite(_Strict):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    permissions: list[str] = Field(default_factory=list)


class RoleResponse(_Strict):
    id: str
    name: str
    description: str
    permissions: list[str] = Field(json_schema_extra={"uniqueItems": True})
    system: bool
    created_at: datetime
    updated_at: datetime
    etag: str


class RolePage(_Strict):
    items: list[RoleResponse]
    next_cursor: str | None


class PermissionCatalogEntry(_Strict):
    name: str
    resource_type: str
    delegable: bool
    description: str


class PermissionCatalogResponse(_Strict):
    version: str
    semantics: dict[str, object]
    permissions: list[PermissionCatalogEntry]


class ResourceScope(_Strict):
    type: Literal["tenant", "storage_space", "directory"]
    storage_space_id: UUID | None = None
    canonical_prefix: str | None = None


class RoleBindingWrite(_Strict):
    principal_id: UUID
    role_id: UUID
    effect: Literal["allow", "deny"]
    scope: ResourceScope
    reason: str = Field(min_length=1, max_length=500)
    starts_at: datetime | None = None
    expires_at: datetime


class RoleBindingResponse(_Strict):
    id: str
    principal: PrincipalSummary
    role_id: str
    effect: Literal["allow", "deny"]
    scope: ResourceScope
    reason: str
    starts_at: datetime
    expires_at: datetime
    created_by: str
    created_at: datetime
    etag: str


class RoleBindingPage(_Strict):
    items: list[RoleBindingResponse]
    next_cursor: str | None


class DecisionSource(_Strict):
    source_type: Literal[
        "role_binding",
        "group",
        "key_scope",
        "directory_policy",
        "tenant_policy",
        "operation_allowlist",
        "default",
    ]
    source_id: str | None
    effect: Literal["allow", "deny"]
    reason_code: str


class EffectivePermission(_Strict):
    permission: str
    decision: Literal["allow", "deny"]
    reason_code: str
    sources: list[DecisionSource]


class EffectivePermissionsResponse(_Strict):
    principal_id: str
    authorization_version: int
    evaluated_at: datetime
    permissions: list[EffectivePermission]


class SimulationRequest(_Strict):
    principal_id: UUID
    permission: str
    storage_space_id: UUID | None = None
    object_key: str | None = None


class AuthorizationDecisionResponse(_Strict):
    permission: str
    decision: Literal["allow", "deny"]
    reason_code: str
    authorization_version: int
    evaluated_at: datetime
    sources: list[DecisionSource]


@router.get(
    "/permission_catalog",
    response_model=PermissionCatalogResponse,
    operation_id="get_permission_catalog",
)
def get_permission_catalog(
    context: Annotated[PrincipalContext, management_permission("get_permission_catalog")],
) -> PermissionCatalogResponse:
    """Return the server-owned permission catalog used by role forms."""
    del context
    catalog_path = Path(__file__).resolve().parents[3] / "contracts" / "permission-catalog.yaml"
    with catalog_path.open(encoding="utf-8") as stream:
        catalog = yaml.safe_load(stream) or {}
    return PermissionCatalogResponse.model_validate(catalog)


def _cursor(value: str | None, context: PrincipalContext, *, query: str) -> UUID | None:
    if value is None:
        return None
    return UUID(
        CursorCodec(b"s3mp-management-cursor-key-v1").decode(
            value,
            context.tenant_id,
            context.principal_id,
            context.authorization_version,
            query=query,
        )
    )


def _page(
    items: list[dict[str, object]], position: UUID | None, context: PrincipalContext, *, query: str
) -> dict[str, object]:
    return {
        "items": items,
        "next_cursor": CursorCodec(b"s3mp-management-cursor-key-v1").encode(
            context.tenant_id,
            context.principal_id,
            context.authorization_version,
            str(position),
            query=query,
        )
        if position
        else None,
    }


@router.get("/groups", response_model=GroupPage, operation_id="list_groups")
async def list_groups(
    context: Annotated[PrincipalContext, management_permission("list_groups")],
    service: Annotated[AuthorizationManagementService, authorization_service],
    cursor: str | None = Query(default=None),
) -> object:
    items, position = await service.list_groups(
        context, cursor=_cursor(cursor, context, query="groups")
    )
    return _page(items, position, context, query="groups")


@router.post("/groups", response_model=GroupResponse, status_code=201, operation_id="create_group")
async def create_group(
    body: GroupWrite,
    context: Annotated[PrincipalContext, management_permission("create_group")],
    service: Annotated[AuthorizationManagementService, authorization_service],
) -> object:
    return await service.create_group(context, body)


@router.get("/groups/{group_id}", response_model=GroupResponse, operation_id="get_group")
async def get_group(
    group_id: UUID,
    context: Annotated[PrincipalContext, management_permission("get_group")],
    service: Annotated[AuthorizationManagementService, authorization_service],
) -> object:
    return await service.get_group(context, group_id)


@router.patch("/groups/{group_id}", response_model=GroupResponse, operation_id="update_group")
async def update_group(
    group_id: UUID,
    body: GroupWrite,
    context: Annotated[PrincipalContext, management_permission("update_group")],
    service: Annotated[AuthorizationManagementService, authorization_service],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> object:
    current = await service.get_group(context, group_id)
    check_etag(current["etag"], require_if_match(if_match))
    return await service.update_group(context, group_id, body)


@router.delete("/groups/{group_id}", status_code=204, operation_id="delete_group")
async def delete_group(
    group_id: UUID,
    context: Annotated[PrincipalContext, management_permission("delete_group")],
    service: Annotated[AuthorizationManagementService, authorization_service],
) -> None:
    await service.delete_group(context, group_id)


@router.get("/roles", response_model=RolePage, operation_id="list_roles")
async def list_roles(
    context: Annotated[PrincipalContext, management_permission("list_roles")],
    service: Annotated[AuthorizationManagementService, authorization_service],
    cursor: str | None = Query(default=None),
) -> object:
    items, position = await service.list_roles(
        context, cursor=_cursor(cursor, context, query="roles")
    )
    return _page(items, position, context, query="roles")


@router.post("/roles", response_model=RoleResponse, status_code=201, operation_id="create_role")
async def create_role(
    body: RoleWrite,
    context: Annotated[PrincipalContext, management_permission("create_role")],
    service: Annotated[AuthorizationManagementService, authorization_service],
) -> object:
    return await service.create_role(context, body)


@router.get("/roles/{role_id}", response_model=RoleResponse, operation_id="get_role")
async def get_role(
    role_id: UUID,
    context: Annotated[PrincipalContext, management_permission("get_role")],
    service: Annotated[AuthorizationManagementService, authorization_service],
) -> object:
    return await service.get_role(context, role_id)


@router.patch("/roles/{role_id}", response_model=RoleResponse, operation_id="update_role")
async def update_role(
    role_id: UUID,
    body: RoleWrite,
    context: Annotated[PrincipalContext, management_permission("update_role")],
    service: Annotated[AuthorizationManagementService, authorization_service],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> object:
    current = await service.get_role(context, role_id)
    check_etag(current["etag"], require_if_match(if_match))
    return await service.update_role(context, role_id, body)


@router.get("/role_bindings", response_model=RoleBindingPage, operation_id="list_role_bindings")
async def list_role_bindings(
    context: Annotated[PrincipalContext, management_permission("list_role_bindings")],
    service: Annotated[AuthorizationManagementService, authorization_service],
    principal_id: UUID | None = None,
    cursor: str | None = Query(default=None),
) -> object:
    items, position = await service.list_role_bindings(
        context,
        principal_id,
        cursor=_cursor(cursor, context, query=f"role_bindings:{principal_id or ''}"),
    )
    return _page(items, position, context, query=f"role_bindings:{principal_id or ''}")


@router.post(
    "/role_bindings",
    response_model=RoleBindingResponse,
    status_code=201,
    operation_id="create_role_binding",
)
async def create_role_binding(
    body: RoleBindingWrite,
    context: Annotated[PrincipalContext, management_permission("create_role_binding")],
    service: Annotated[AuthorizationManagementService, authorization_service],
) -> object:
    return await service.create_role_binding(context, body)


@router.get(
    "/role_bindings/{role_binding_id}",
    response_model=RoleBindingResponse,
    operation_id="get_role_binding",
)
async def get_role_binding(
    role_binding_id: UUID,
    context: Annotated[PrincipalContext, management_permission("get_role_binding")],
    service: Annotated[AuthorizationManagementService, authorization_service],
) -> object:
    return await service.get_role_binding(context, role_binding_id)


@router.delete(
    "/role_bindings/{role_binding_id}", status_code=204, operation_id="revoke_role_binding"
)
async def revoke_role_binding(
    role_binding_id: UUID,
    context: Annotated[PrincipalContext, management_permission("revoke_role_binding")],
    service: Annotated[AuthorizationManagementService, authorization_service],
) -> None:
    await service.revoke_role_binding(context, role_binding_id)


@router.get(
    "/principals/{principal_id}/effective_permissions",
    response_model=EffectivePermissionsResponse,
    operation_id="get_effective_permissions",
)
async def get_effective_permissions(
    principal_id: UUID,
    context: Annotated[PrincipalContext, management_permission("get_effective_permissions")],
    service: Annotated[AuthorizationManagementService, authorization_service],
    storage_space_id: UUID | None = None,
    object_key: str | None = None,
) -> object:
    return await service.get_effective_permissions(
        context, principal_id, storage_space_id, object_key
    )


@router.post(
    "/authorization/simulations",
    response_model=AuthorizationDecisionResponse,
    operation_id="simulate_authorization",
)
async def simulate_authorization(
    body: SimulationRequest,
    context: Annotated[PrincipalContext, management_permission("simulate_authorization")],
    service: Annotated[AuthorizationManagementService, authorization_service],
) -> object:
    return await service.simulate_authorization(context, body)
