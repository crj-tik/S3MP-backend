"""Applications and API Key HTTP endpoints."""

from typing import Any

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, ConfigDict, Field

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
async def list_applications(request: Request) -> Any:
    return await _app_service(request).list_apps(_context(request))


@router.post("/applications", status_code=201, operation_id="create_application")
async def create_application(
    request: Request,
    body: ApplicationCreate,
) -> Any:
    return await _app_service(request).create_app(_context(request), body.name)


@router.get("/applications/{application_id}", operation_id="get_application")
async def get_application(
    request: Request,
    application_id: str = Path(min_length=1),
) -> Any:
    return await _app_service(request).get_app(_context(request), application_id)


@router.patch("/applications/{application_id}", operation_id="update_application")
async def update_application(
    request: Request,
    body: ApplicationUpdate,
    application_id: str = Path(min_length=1),
) -> Any:
    return await _app_service(request).update_app(
        _context(request), application_id, body.name
    )


# ── API Keys ──────────────────────────────────────────────────────────────────


@router.get("/applications/{application_id}/api_keys", operation_id="list_api_keys")
async def list_api_keys(
    request: Request,
    application_id: str = Path(min_length=1),
) -> Any:
    return await _key_service(request).list_keys(_context(request), application_id)


@router.post("/applications/{application_id}/api_keys", status_code=201, operation_id="create_api_key")
async def create_api_key(
    request: Request,
    body: ApiKeyCreate,
    application_id: str = Path(min_length=1),
) -> Any:
    return await _key_service(request).issue(
        _context(request), application_id, body.scopes, body.ttl_days
    )


@router.get("/api_keys/{api_key_id}", operation_id="get_api_key")
async def get_api_key(
    request: Request,
    api_key_id: str = Path(min_length=1),
) -> Any:
    return await _key_service(request).get_key(_context(request), api_key_id)


@router.get("/api_keys/{api_key_id}/secret", status_code=410, operation_id="get_api_key_secret")
async def get_api_key_secret(
    request: Request,
    api_key_id: str = Path(min_length=1),
) -> Any:
    raise ApiError("secret_not_retrievable", "API key secrets are only shown once at creation", status_code=410)


@router.post("/api_keys/{api_key_id}/rotations", status_code=201, operation_id="rotate_api_key")
async def rotate_api_key(
    request: Request,
    body: ApiKeyRotate,
    api_key_id: str = Path(min_length=1),
) -> Any:
    return await _key_service(request).rotate(
        _context(request), api_key_id, body.overlap_seconds
    )


@router.post("/api_keys/{api_key_id}/revocations", operation_id="revoke_api_key")
async def revoke_api_key(
    request: Request,
    body: ApiKeyRevoke,
    api_key_id: str = Path(min_length=1),
) -> Any:
    return await _key_service(request).revoke(_context(request), api_key_id, body.reason)
