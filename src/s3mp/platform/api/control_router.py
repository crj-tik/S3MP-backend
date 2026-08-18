"""Platform control-plane read endpoints with explicit, safe response models."""

import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.cursor import CursorCodec
from s3mp.common.api.dependencies import application_service
from s3mp.common.errors import ApiError
from s3mp.platform.api.dependencies import platform_permission
from s3mp.platform.api.tenant_router import PlatformTenantResponse
from s3mp.platform.application.control_plane import PlatformControlPlaneService
from s3mp.platform.domain.context import PlatformContext
from s3mp.platform.domain.support_access import SupportAccessStatus

router = APIRouter(prefix="/api/v1/platform", tags=["Platform control plane"])
control_service = application_service("platform_control_plane")
_codec = CursorCodec(b"s3mp-management-cursor-key-v1")
_platform_tenant = UUID(int=0)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountSummary(_Strict):
    id: UUID
    email: str
    employee_number: str | None
    display_name: str
    status: str
    created_at: datetime | None
    updated_at: datetime | None
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None
    deletion_reason: str | None = None


class AccountPage(_Strict):
    items: list[AccountSummary]
    next_cursor: str | None = None


class LifecycleRequest(_Strict):
    reason: str = Field(min_length=1, max_length=500)


class PlatformRoleResponse(_Strict):
    id: UUID
    name: str
    permissions: list[str]
    built_in: bool
    created_at: datetime | None


class PlatformRolePage(_Strict):
    items: list[PlatformRoleResponse]
    next_cursor: str | None = None


class PlatformRoleBindingResponse(_Strict):
    id: UUID
    user: AccountSummary
    role: PlatformRoleResponse
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime | None


class PlatformRoleBindingPage(_Strict):
    items: list[PlatformRoleBindingResponse]
    next_cursor: str | None = None


class SupportAccessResponse(_Strict):
    id: UUID
    requester: AccountSummary
    approver: AccountSummary | None
    tenant: PlatformTenantResponse
    reason: str
    status: Literal["pending", "approved", "revoked", "expired"]
    expires_at: datetime
    approved_at: datetime | None
    approved_by_user_id: UUID | None
    membership_id: UUID | None
    role_binding_id: UUID | None
    revoked_at: datetime | None
    created_at: datetime | None


class SupportAccessPage(_Strict):
    items: list[SupportAccessResponse]
    next_cursor: str | None = None


class PlatformAuditEventResponse(_Strict):
    id: UUID
    actor_user_id: UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    details: dict[str, object]
    created_at: datetime | None


class PlatformAuditEventPage(_Strict):
    items: list[PlatformAuditEventResponse]
    next_cursor: str | None = None


def _cursor(value: str | None, context: PlatformContext, *, query: str) -> UUID | None:
    if value is None:
        return None
    position = _codec.decode(value, _platform_tenant, context.user_id, 1, query=query)
    try:
        return UUID(position)
    except ValueError as exc:
        raise ApiError("invalid_cursor", "Invalid platform cursor", 400) from exc


def _next(position: UUID | None, context: PlatformContext, *, query: str) -> str | None:
    return (
        _codec.encode(_platform_tenant, context.user_id, 1, str(position), query=query)
        if position
        else None
    )


def _query_scope(operation: str, **filters: str | None) -> str:
    """Bind opaque cursors to the exact operation and normalized filters."""
    normalized = {key: value.strip() if value else None for key, value in filters.items()}
    return f"{operation}:{json.dumps(normalized, sort_keys=True, separators=(',', ':'))}"


AccountsContext = Annotated[
    PlatformContext, platform_permission("platform.accounts.read", "list_platform_accounts")
]
AccountDetailContext = Annotated[
    PlatformContext, platform_permission("platform.accounts.read", "get_platform_account")
]
AccountManageContext = Annotated[
    PlatformContext, platform_permission("platform.accounts.manage", "manage_platform_accounts")
]
RolesContext = Annotated[
    PlatformContext, platform_permission("platform.roles.read", "list_platform_roles")
]
RoleBindingsContext = Annotated[
    PlatformContext, platform_permission("platform.roles.read", "list_platform_role_bindings")
]
SupportContext = Annotated[
    PlatformContext, platform_permission("platform.support.read", "list_support_access")
]
SupportDetailContext = Annotated[
    PlatformContext, platform_permission("platform.support.read", "get_support_access")
]
AuditContext = Annotated[
    PlatformContext, platform_permission("platform.audit.read", "list_platform_audit_events")
]
AuditDetailContext = Annotated[
    PlatformContext, platform_permission("platform.audit.read", "get_platform_audit_event")
]


@router.get("/accounts", response_model=AccountPage, operation_id="list_platform_accounts")
async def list_accounts(
    context: AccountsContext,
    service: Annotated[PlatformControlPlaneService, control_service],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    query: str | None = Query(default=None, min_length=1, max_length=320),
    status: Literal["active", "disabled"] | None = Query(default=None),
    include_deleted: bool = Query(default=False),
) -> AccountPage:
    scope = _query_scope("platform_accounts", query=query, status=status)
    items, position = await service.list_accounts(
        context,
        limit=limit,
        cursor=_cursor(cursor, context, query=scope),
        query=query,
        status=status,
        include_deleted=include_deleted,
    )
    return AccountPage(
        items=[AccountSummary.model_validate(item) for item in items],
        next_cursor=_next(position, context, query=scope),
    )


@router.get(
    "/accounts/{user_id}", response_model=AccountSummary, operation_id="get_platform_account"
)
async def get_account(
    user_id: UUID,
    context: AccountDetailContext,
    service: Annotated[PlatformControlPlaneService, control_service],
) -> AccountSummary:
    item = await service.get_account(context, user_id)
    if item is None:
        raise ApiError("resource_not_found", "Platform account not found", 404)
    return AccountSummary.model_validate(item)


@router.delete(
    "/accounts/{user_id}", response_model=AccountSummary, operation_id="delete_platform_account"
)
async def delete_account(
    user_id: UUID,
    body: LifecycleRequest,
    context: AccountManageContext,
    service: Annotated[PlatformControlPlaneService, control_service],
) -> AccountSummary:
    return AccountSummary.model_validate(
        await service.delete_account(context, user_id, body.reason)
    )


@router.post(
    "/accounts/{user_id}/restore",
    response_model=AccountSummary,
    operation_id="restore_platform_account",
)
async def restore_account(
    user_id: UUID,
    body: LifecycleRequest,
    context: AccountManageContext,
    service: Annotated[PlatformControlPlaneService, control_service],
) -> AccountSummary:
    return AccountSummary.model_validate(
        await service.restore_account(context, user_id, body.reason)
    )


@router.get("/roles", response_model=PlatformRolePage, operation_id="list_platform_roles")
async def list_roles(
    context: RolesContext,
    service: Annotated[PlatformControlPlaneService, control_service],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> PlatformRolePage:
    items, position = await service.list_roles(
        context, limit=limit, cursor=_cursor(cursor, context, query="platform_roles")
    )
    return PlatformRolePage(
        items=[PlatformRoleResponse.model_validate(item) for item in items],
        next_cursor=_next(position, context, query="platform_roles"),
    )


@router.get(
    "/role-bindings",
    response_model=PlatformRoleBindingPage,
    operation_id="list_platform_role_bindings",
)
async def list_role_bindings(
    context: RoleBindingsContext,
    service: Annotated[PlatformControlPlaneService, control_service],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> PlatformRoleBindingPage:
    items, position = await service.list_role_bindings(
        context, limit=limit, cursor=_cursor(cursor, context, query="platform_role_bindings")
    )
    return PlatformRoleBindingPage(
        items=[PlatformRoleBindingResponse.model_validate(item) for item in items],
        next_cursor=_next(position, context, query="platform_role_bindings"),
    )


@router.get("/support-access", response_model=SupportAccessPage, operation_id="list_support_access")
async def list_support_access(
    context: SupportContext,
    service: Annotated[PlatformControlPlaneService, control_service],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    status: Annotated[SupportAccessStatus | None, Query()] = None,
) -> SupportAccessPage:
    scope = _query_scope("platform_support_access", status=status)
    items, position = await service.list_support(
        context,
        limit=limit,
        cursor=_cursor(cursor, context, query=scope),
        status=status,
    )
    return SupportAccessPage(
        items=[SupportAccessResponse.model_validate(item) for item in items],
        next_cursor=_next(position, context, query=scope),
    )


@router.get(
    "/support-access/{request_id}",
    response_model=SupportAccessResponse,
    operation_id="get_support_access",
)
async def get_support_access(
    request_id: UUID,
    context: SupportDetailContext,
    service: Annotated[PlatformControlPlaneService, control_service],
) -> SupportAccessResponse:
    item = await service.get_support(context, request_id)
    if item is None:
        raise ApiError("resource_not_found", "Support access request not found", 404)
    return SupportAccessResponse.model_validate(item)


@router.get(
    "/audit-events",
    response_model=PlatformAuditEventPage,
    operation_id="list_platform_audit_events",
)
async def list_audit_events(
    context: AuditContext,
    service: Annotated[PlatformControlPlaneService, control_service],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    action: str | None = Query(default=None, max_length=160),
    resource_type: str | None = Query(default=None, max_length=80),
    resource_id: str | None = Query(default=None, max_length=120),
) -> PlatformAuditEventPage:
    action = action.strip() if action else None
    resource_type = resource_type.strip() if resource_type else None
    resource_id = resource_id.strip() if resource_id else None
    scope = _query_scope(
        "platform_audit_events",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    items, position = await service.list_audit(
        context,
        limit=limit,
        cursor=_cursor(cursor, context, query=scope),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    return PlatformAuditEventPage(
        items=[PlatformAuditEventResponse.model_validate(item) for item in items],
        next_cursor=_next(position, context, query=scope),
    )


@router.get(
    "/audit-events/{event_id}",
    response_model=PlatformAuditEventResponse,
    operation_id="get_platform_audit_event",
)
async def get_audit_event(
    event_id: UUID,
    context: AuditDetailContext,
    service: Annotated[PlatformControlPlaneService, control_service],
) -> PlatformAuditEventResponse:
    item = await service.get_audit(context, event_id)
    if item is None:
        raise ApiError("resource_not_found", "Platform audit event not found", 404)
    return PlatformAuditEventResponse.model_validate(item)
