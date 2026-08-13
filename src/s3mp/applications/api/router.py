"""Applications and API Key HTTP endpoints."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.dependencies import management_permission
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Applications", "API Keys"])


# ── DTOs ──────────────────────────────────────────────────────────────────────


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class ApplicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=200)


class ApplicationTakeover(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scopes: list[str] = Field(default_factory=list)
    ttl_days: int = Field(default=90, ge=1, le=365)


class ApiKeyRotate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overlap_seconds: int = Field(default=300, ge=0, le=86400)


class ApiKeyRevoke(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


# ── Dependencies ──────────────────────────────────────────────────────────────


def _context(request: Request) -> PrincipalContext:
    context = getattr(request.state, "principal_context", None)
    if not isinstance(context, PrincipalContext):
        raise ApiError("authentication_required", "Authentication required", status_code=401)
    return context


def _app_service(request: Request) -> Any:
    svc = getattr(request.app.state, "application_service", None)
    if svc is None:
        raise ApiError("internal_error", "Application service is not configured", status_code=500)
    return svc


def _key_service(request: Request) -> Any:
    svc = getattr(request.app.state, "api_key_service", None)
    if svc is None:
        raise ApiError("internal_error", "API key service is not configured", status_code=500)
    return svc


# ── Applications ──────────────────────────────────────────────────────────────


@router.get("/applications", operation_id="list_applications")
async def list_applications(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("list_applications")],
) -> Any:
    return await _app_service(request).list_apps(context)


@router.post("/applications", status_code=201, operation_id="create_application")
async def create_application(
    request: Request,
    body: ApplicationCreate,
    context: Annotated[PrincipalContext, management_permission("create_application")],
) -> Any:
    return await _app_service(request).create_app(context, body.name)


@router.get("/applications/{application_id}", operation_id="get_application")
async def get_application(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("get_application")],
    application_id: UUID,
) -> Any:
    return await _app_service(request).get_app(context, application_id)


@router.patch("/applications/{application_id}", operation_id="update_application")
async def update_application(
    request: Request,
    body: ApplicationUpdate,
    context: Annotated[PrincipalContext, management_permission("update_application")],
    application_id: str = Path(min_length=1),
) -> Any:
    return await _app_service(request).update_app(
        context, application_id, body.name
    )


@router.post("/applications/{application_id}/takeover", operation_id="takeover_application")
async def takeover_application(
    request: Request,
    body: ApplicationTakeover,
    context: Annotated[PrincipalContext, management_permission("takeover_application")],
    application_id: UUID,
) -> Any:
    return await _app_service(request).takeover_app(context, application_id, body.reason)


# ── API Keys ──────────────────────────────────────────────────────────────────


@router.get("/applications/{application_id}/api_keys", operation_id="list_api_keys")
async def list_api_keys(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("list_api_keys")],
    application_id: str = Path(min_length=1),
) -> Any:
    return await _key_service(request).list_keys(context, application_id)


@router.post("/applications/{application_id}/api_keys", status_code=201, operation_id="create_api_key")
async def create_api_key(
    request: Request,
    body: ApiKeyCreate,
    context: Annotated[PrincipalContext, management_permission("create_api_key")],
    application_id: str = Path(min_length=1),
) -> Any:
    return await _key_service(request).issue(
        context, application_id, body.scopes, body.ttl_days
    )


@router.get("/api_keys/{api_key_id}", operation_id="get_api_key")
async def get_api_key(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("get_api_key")],
    api_key_id: str = Path(min_length=1),
) -> Any:
    return await _key_service(request).get_key(context, api_key_id)


@router.get("/api_keys/{api_key_id}/secret", status_code=410, operation_id="get_api_key_secret")
async def get_api_key_secret(
    request: Request,
    _context: Annotated[PrincipalContext, management_permission("get_api_key_secret")],
    api_key_id: str = Path(min_length=1),
) -> Any:
    raise ApiError("secret_not_retrievable", "API key secrets are only shown once at creation", status_code=410)


@router.post("/api_keys/{api_key_id}/rotations", status_code=201, operation_id="rotate_api_key")
async def rotate_api_key(
    request: Request,
    body: ApiKeyRotate,
    context: Annotated[PrincipalContext, management_permission("rotate_api_key")],
    api_key_id: str = Path(min_length=1),
) -> Any:
    return await _key_service(request).rotate(
        context, api_key_id, body.overlap_seconds
    )


@router.post("/api_keys/{api_key_id}/revocations", operation_id="revoke_api_key")
async def revoke_api_key(
    request: Request,
    body: ApiKeyRevoke,
    context: Annotated[PrincipalContext, management_permission("revoke_api_key")],
    api_key_id: str = Path(min_length=1),
) -> Any:
    return await _key_service(request).revoke(context, api_key_id, body.reason)
