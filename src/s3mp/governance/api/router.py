"""Quota and audit HTTP endpoints."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.cursor import CursorCodec
from s3mp.common.api.dependencies import management_permission
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Quotas", "Audit"])


# ── DTOs ──────────────────────────────────────────────────────────────────────


class QuotaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit_bytes: int = Field(ge=0)


class QuotaResponse(BaseModel):
    """租户或应用范围的存储配额及当前用量。"""

    id: str = Field(description="配额记录的稳定标识。")
    tenant_id: str | None = Field(default=None, description="该配额所属租户的稳定标识。")
    storage_space_id: str | None = Field(
        default=None,
        description="兼容迁移期间关联的逻辑存储空间标识；应用配额以 application_id 为准。",
    )
    application_id: str | None = Field(
        default=None,
        description="应用的稳定标识。一个逻辑存储空间只绑定一个应用。",
    )
    limit_bytes: int | None = Field(
        default=None, description="允许使用和预留的容量上限，单位为字节。"
    )
    used_bytes: int | None = Field(default=None, description="已验证并确认入库的容量，单位为字节。")
    reserved_bytes: int | None = Field(
        default=None, description="进行中上传暂时占用的容量，单位为字节。"
    )
    available_bytes: int | None = Field(
        default=None,
        description="当前可继续预留的容量，等于上限减去已用量和预留量，单位为字节。",
    )
    measured_at: datetime | None = Field(
        default=None,
        description="本次用量计算或读取的时间。",
    )
    scope_type: str | None = Field(
        default=None,
        description="配额范围：tenant 表示租户总量，application 表示单个应用。",
    )
    updated_at: datetime | None = Field(default=None, description="配额记录最后更新的时间。")


class AuditActor(BaseModel):
    principal_id: str
    principal_type: str


class AuditEventResponse(BaseModel):
    """租户内审计事件；`details` 是该事件类型的补充上下文。"""

    id: str
    tenant_id: str | None = None
    actor_principal_id: str | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None
    actor: AuditActor | None = None
    outcome: str | None = None
    request_id: str | None = None


class QuotaPage(BaseModel):
    items: list[QuotaResponse]
    next_cursor: str | None = None


class AuditEventPage(BaseModel):
    items: list[AuditEventResponse]
    next_cursor: str | None = None


def _page(
    items: list[dict[str, Any]], position: str | None, context: PrincipalContext, *, query: str
) -> dict[str, Any]:
    return {
        "items": items,
        "next_cursor": CursorCodec(b"s3mp-management-cursor-key-v1").encode(
            context.tenant_id,
            context.principal_id,
            context.authorization_version,
            position,
            query=query,
        )
        if position
        else None,
    }


def _cursor(value: str | None, context: PrincipalContext, *, query: str) -> str | None:
    if value is None:
        return None
    return CursorCodec(b"s3mp-management-cursor-key-v1").decode(
        value,
        context.tenant_id,
        context.principal_id,
        context.authorization_version,
        query=query,
    )


# ── Dependencies ──────────────────────────────────────────────────────────────


def _context(request: Request) -> PrincipalContext:
    context = getattr(request.state, "principal_context", None)
    if not isinstance(context, PrincipalContext):
        raise ApiError("authentication_required", "Authentication required", status_code=401)
    return context


def _quota_svc(request: Request) -> Any:
    svc = getattr(request.app.state, "quota_service", None)
    if svc is None:
        raise ApiError("internal_error", "Quota service is not configured", status_code=500)
    return svc


def _audit_svc(request: Request) -> Any:
    svc = getattr(request.app.state, "audit_service", None)
    if svc is None:
        raise ApiError("internal_error", "Audit service is not configured", status_code=500)
    return svc


# ── Quotas ────────────────────────────────────────────────────────────────────


@router.get("/quotas", response_model=QuotaPage, operation_id="list_quotas")
async def list_quotas(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("list_quotas")],
    storage_space_id: str | None = None,
    application_id: str | None = None,
    cursor: str | None = Query(default=None),
) -> QuotaPage:
    query = f"quotas:{storage_space_id or 'all'}:{application_id or 'all'}"
    quota_kwargs: dict[str, Any] = {
        "cursor": _cursor(cursor, context, query=query),
    }
    if application_id is not None:
        quota_kwargs["application_id"] = application_id
    items, position = await _quota_svc(request).list_quotas(
        context, storage_space_id, **quota_kwargs
    )
    return QuotaPage.model_validate(_page(items, position, context, query=query))


@router.get("/quotas/{quota_id}", response_model=QuotaResponse, operation_id="get_quota")
async def get_quota(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("get_quota")],
    quota_id: str = Path(min_length=1),
) -> QuotaResponse:
    return QuotaResponse.model_validate(await _quota_svc(request).get_quota(context, quota_id))


@router.patch("/quotas/{quota_id}", response_model=QuotaResponse, operation_id="update_quota")
async def update_quota(
    request: Request,
    body: QuotaUpdate,
    context: Annotated[PrincipalContext, management_permission("update_quota")],
    quota_id: str = Path(min_length=1),
) -> QuotaResponse:
    return QuotaResponse.model_validate(
        await _quota_svc(request).update_quota(context, quota_id, body.limit_bytes)
    )


# ── Audit ─────────────────────────────────────────────────────────────────────


@router.get("/audit_events", response_model=AuditEventPage, operation_id="list_audit_events")
async def list_audit_events(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("list_audit_events")],
    occurred_from: str | None = None,
    occurred_to: str | None = None,
    action: str | None = None,
    actor_principal_id: str | None = None,
    cursor: str | None = Query(default=None),
) -> AuditEventPage:
    query = f"audit_events:{occurred_from}:{occurred_to}:{action}:{actor_principal_id}"
    items, position = await _audit_svc(request).list_audit_events(
        context,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        action=action,
        actor_principal_id=actor_principal_id,
        cursor=_cursor(cursor, context, query=query),
    )
    return AuditEventPage.model_validate(_page(items, position, context, query=query))


@router.get(
    "/audit_events/{audit_event_id}",
    response_model=AuditEventResponse,
    operation_id="get_audit_event",
)
async def get_audit_event(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("get_audit_event")],
    audit_event_id: str = Path(min_length=1),
) -> AuditEventResponse:
    return AuditEventResponse.model_validate(
        await _audit_svc(request).get_audit_event(context, audit_event_id)
    )
