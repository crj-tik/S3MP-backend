"""Application and tenant-admin directory exclusion endpoints."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.dependencies import management_permission
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Knowledge Extraction"])


class ExclusionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    directory_path: str = Field(min_length=1, max_length=1024)


class ExclusionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    application_id: UUID
    directory_path: str
    rule_source: str
    enabled: bool


def _store(request: Request) -> Any:
    store = getattr(request.app.state, "knowledge_store", None)
    if store is None:
        raise ApiError("internal_error", "Knowledge store is not configured", status_code=500)
    return store


def _context(request: Request) -> PrincipalContext:
    context = getattr(request.state, "principal_context", None)
    if not isinstance(context, PrincipalContext):
        raise ApiError("authentication_required", "Authentication required", status_code=401)
    return context


def _require_application_scope(context: PrincipalContext) -> None:
    if context.subject_kind != "application" or context.application_id is None:
        raise ApiError("permission_denied", "Application API key is required", status_code=403)
    if (
        context.api_key_scopes is None
        or "knowledge.exclusions.manage" not in context.api_key_scopes
    ):
        raise ApiError(
            "permission_denied",
            "API key scope does not allow exclusion management",
            status_code=403,
        )


@router.get(
    "/knowledge/exclusions",
    response_model=list[ExclusionResponse],
    operation_id="list_knowledge_exclusions_application",
)
async def list_application_exclusions(request: Request) -> list[ExclusionResponse]:
    context = _context(request)
    _require_application_scope(context)
    rows = await _store(request).list_exclusions(context.tenant_id, context.application_id)
    return [
        ExclusionResponse.model_validate(row)
        for row in rows
        if row["rule_source"] == "application_api"
    ]


@router.post(
    "/knowledge/exclusions",
    response_model=ExclusionResponse,
    status_code=201,
    operation_id="create_knowledge_exclusion_application",
)
async def create_application_exclusion(
    request: Request, body: Annotated[ExclusionCreate, Body()]
) -> ExclusionResponse:
    context = _context(request)
    _require_application_scope(context)
    row = await _store(request).create_exclusion(
        tenant_id=context.tenant_id,
        application_id=context.application_id,
        directory_path=body.directory_path,
        rule_source="application_api",
        created_by_principal_id=context.principal_id,
    )
    return ExclusionResponse.model_validate(row)


@router.delete(
    "/knowledge/exclusions/{rule_id}",
    status_code=204,
    operation_id="delete_knowledge_exclusion_application",
)
async def delete_application_exclusion(request: Request, rule_id: Annotated[UUID, Path()]) -> None:
    context = _context(request)
    _require_application_scope(context)
    deleted = await _store(request).delete_exclusion(
        context.tenant_id,
        context.application_id,
        rule_id,
        "application_api",
        context.principal_id,
    )
    if not deleted:
        raise ApiError("resource_not_found", "Exclusion rule not found", status_code=404)


@router.get(
    "/knowledge/tenant-exclusions/{application_id}",
    response_model=list[ExclusionResponse],
    operation_id="list_knowledge_exclusions_tenant_admin",
    dependencies=[management_permission("list_knowledge_exclusions_tenant_admin")],
)
async def list_tenant_exclusions(
    request: Request, application_id: Annotated[UUID, Path()]
) -> list[ExclusionResponse]:
    context = _context(request)
    rows = await _store(request).list_exclusions(context.tenant_id, application_id)
    return [
        ExclusionResponse.model_validate(row)
        for row in rows
        if row["rule_source"] == "tenant_admin"
    ]


@router.post(
    "/knowledge/tenant-exclusions/{application_id}",
    response_model=ExclusionResponse,
    status_code=201,
    operation_id="create_knowledge_exclusion_tenant_admin",
    dependencies=[management_permission("create_knowledge_exclusion_tenant_admin")],
)
async def create_tenant_exclusion(
    request: Request,
    application_id: Annotated[UUID, Path()],
    body: Annotated[ExclusionCreate, Body()],
) -> ExclusionResponse:
    context = _context(request)
    row = await _store(request).create_exclusion(
        tenant_id=context.tenant_id,
        application_id=application_id,
        directory_path=body.directory_path,
        rule_source="tenant_admin",
        created_by_principal_id=context.principal_id,
    )
    return ExclusionResponse.model_validate(row)


@router.delete(
    "/knowledge/tenant-exclusions/{application_id}/{rule_id}",
    status_code=204,
    operation_id="delete_knowledge_exclusion_tenant_admin",
    dependencies=[management_permission("delete_knowledge_exclusion_tenant_admin")],
)
async def delete_tenant_exclusion(
    request: Request,
    application_id: Annotated[UUID, Path()],
    rule_id: Annotated[UUID, Path()],
) -> None:
    context = _context(request)
    deleted = await _store(request).delete_exclusion(
        context.tenant_id,
        application_id,
        rule_id,
        "tenant_admin",
        context.principal_id,
    )
    if not deleted:
        raise ApiError("resource_not_found", "Exclusion rule not found", status_code=404)
