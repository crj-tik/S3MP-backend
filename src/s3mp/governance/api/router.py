"""Quota and audit HTTP endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.dependencies import management_permission
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Quotas", "Audit"])


# ── DTOs ──────────────────────────────────────────────────────────────────────


class QuotaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit_bytes: int = Field(ge=0)


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


@router.get("/quotas", operation_id="list_quotas")
async def list_quotas(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("list_quotas")],
    storage_space_id: str | None = None,
) -> Any:
    return await _quota_svc(request).list_quotas(
        context, storage_space_id
    )


@router.get("/quotas/{quota_id}", operation_id="get_quota")
async def get_quota(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("get_quota")],
    quota_id: str = Path(min_length=1),
) -> Any:
    return await _quota_svc(request).get_quota(
        context, quota_id
    )


@router.patch("/quotas/{quota_id}", operation_id="update_quota")
async def update_quota(
    request: Request,
    body: QuotaUpdate,
    context: Annotated[PrincipalContext, management_permission("update_quota")],
    quota_id: str = Path(min_length=1),
) -> Any:
    return await _quota_svc(request).update_quota(
        context, quota_id, body.limit_bytes
    )


# ── Audit ─────────────────────────────────────────────────────────────────────


@router.get("/audit_events", operation_id="list_audit_events")
async def list_audit_events(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("list_audit_events")],
    occurred_from: str | None = None,
    occurred_to: str | None = None,
    action: str | None = None,
    actor_principal_id: str | None = None,
) -> Any:
    return await _audit_svc(request).list_audit_events(
        context,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        action=action,
        actor_principal_id=actor_principal_id,
    )


@router.get("/audit_events/{audit_event_id}", operation_id="get_audit_event")
async def get_audit_event(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("get_audit_event")],
    audit_event_id: str = Path(min_length=1),
) -> Any:
    return await _audit_svc(request).get_audit_event(
        context, audit_event_id
    )
