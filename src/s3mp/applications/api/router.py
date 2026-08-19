"""Applications and API Key HTTP endpoints."""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from s3mp.applications.infrastructure.models import ApiKeyStatus, ApplicationStatus
from s3mp.common.api.cursor import CursorCodec
from s3mp.common.api.dependencies import management_permission
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Applications", "API Keys"])


# ── DTOs ──────────────────────────────────────────────────────────────────────


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    authorization_membership_id: UUID | None = Field(
        default=None,
        description="同租户 active Membership 的授权代表；省略时使用当前登录成员。",
    )


class ApplicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=200)


class ApplicationTakeover(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class ApplicationLifecycleRequest(BaseModel):
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


class ApplicationResponse(BaseModel):
    """租户内应用的公开管理信息。"""

    id: UUID
    tenant_id: UUID | None = None
    principal_id: UUID | None = None
    name: str
    storage_namespace: str | None = Field(
        default=None,
        description="应用不可变的共享 Bucket 命名空间；与相对对象路径共同派生物理对象 Key。",
    )
    status: str | None = None
    authorization_version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None
    deletion_reason: str | None = None
    owners: list[dict[str, str]] = Field(default_factory=list)
    takeover_required: bool = False
    authorization_state: str = "authorization_unconfigured"
    authorization_representative: dict[str, Any] | None = None


class ApplicationMembershipBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    membership_id: UUID


class ApiKeyResponse(BaseModel):
    """API 密钥元数据；常规查询绝不返回明文 `secret`。"""

    id: UUID
    tenant_id: UUID | None = None
    application_id: UUID | None = None
    key_id: str | None = None
    prefix: str | None = None
    pepper_version: int | None = None
    scopes: list[str] = Field(default_factory=list)
    status: str | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime | None = None


class ApiKeyIssuedResponse(ApiKeyResponse):
    """仅创建或轮换时返回一次的 API 密钥明文。"""

    secret: str
    credential: str


class ApplicationPage(BaseModel):
    items: list[ApplicationResponse]
    next_cursor: str | None = None


class ApiKeyPage(BaseModel):
    items: list[ApiKeyResponse]
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


def _decode_cursor(value: str | None, context: PrincipalContext, *, query: str) -> str | None:
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


@router.get("/applications", response_model=ApplicationPage, operation_id="list_applications")
async def list_applications(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("list_applications")],
    cursor: str | None = Query(default=None),
    status: Annotated[ApplicationStatus, Query()] = ApplicationStatus.ACTIVE,
) -> ApplicationPage:
    query = f"applications:{status.value}"
    items, position = await _app_service(request).list_apps(
        context, cursor=_decode_cursor(cursor, context, query=query), status=status
    )
    return ApplicationPage.model_validate(_page(items, position, context, query=query))


@router.post(
    "/applications",
    status_code=201,
    response_model=ApplicationResponse,
    operation_id="create_application",
)
async def create_application(
    request: Request,
    body: ApplicationCreate,
    context: Annotated[PrincipalContext, management_permission("create_application")],
) -> ApplicationResponse:
    service = _app_service(request)
    if body.authorization_membership_id is None:
        result = await service.create_app(context, body.name)
    else:
        result = await service.create_app(
            context, body.name, body.authorization_membership_id
        )
    return ApplicationResponse.model_validate(
        result
    )


@router.get(
    "/applications/{application_id}/authorization-representative",
    response_model=dict[str, Any],
    operation_id="get_application_authorization_representative",
)
async def get_application_authorization_representative(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("get_application")],
    application_id: UUID,
) -> dict[str, Any]:
    return await _app_service(request).get_membership_binding(context, application_id)


@router.put(
    "/applications/{application_id}/authorization-representative",
    response_model=dict[str, Any],
    operation_id="bind_application_authorization_representative",
)
async def bind_application_authorization_representative(
    request: Request,
    body: ApplicationMembershipBindingRequest,
    context: Annotated[PrincipalContext, management_permission("update_application")],
    application_id: UUID,
) -> dict[str, Any]:
    return await _app_service(request).bind_membership(
        context, application_id, body.membership_id
    )


@router.delete(
    "/applications/{application_id}/authorization-representative",
    response_model=dict[str, Any],
    operation_id="revoke_application_authorization_representative",
)
async def revoke_application_authorization_representative(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("update_application")],
    application_id: UUID,
) -> dict[str, Any]:
    return await _app_service(request).revoke_membership_binding(context, application_id)


@router.get(
    "/applications/{application_id}",
    response_model=ApplicationResponse,
    operation_id="get_application",
)
async def get_application(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("get_application")],
    application_id: UUID,
) -> ApplicationResponse:
    return ApplicationResponse.model_validate(
        await _app_service(request).get_app(context, application_id)
    )


@router.patch(
    "/applications/{application_id}",
    response_model=ApplicationResponse,
    operation_id="update_application",
)
async def update_application(
    request: Request,
    body: ApplicationUpdate,
    context: Annotated[PrincipalContext, management_permission("update_application")],
    application_id: UUID,
) -> ApplicationResponse:
    return ApplicationResponse.model_validate(
        await _app_service(request).update_app(context, application_id, body.name)
    )


@router.post(
    "/applications/{application_id}/takeover",
    response_model=ApplicationResponse,
    operation_id="takeover_application",
)
async def takeover_application(
    request: Request,
    body: ApplicationTakeover,
    context: Annotated[PrincipalContext, management_permission("takeover_application")],
    application_id: UUID,
) -> ApplicationResponse:
    return ApplicationResponse.model_validate(
        await _app_service(request).takeover_app(context, application_id, body.reason)
    )


@router.delete(
    "/applications/{application_id}",
    response_model=ApplicationResponse,
    operation_id="delete_application",
)
async def delete_application(
    request: Request,
    body: ApplicationLifecycleRequest,
    context: Annotated[PrincipalContext, management_permission("delete_application")],
    application_id: UUID,
) -> ApplicationResponse:
    return ApplicationResponse.model_validate(
        await _app_service(request).delete_app(context, application_id, body.reason)
    )


@router.post(
    "/applications/{application_id}/restore",
    response_model=ApplicationResponse,
    operation_id="restore_application",
)
async def restore_application(
    request: Request,
    body: ApplicationLifecycleRequest,
    context: Annotated[PrincipalContext, management_permission("restore_application")],
    application_id: UUID,
) -> ApplicationResponse:
    return ApplicationResponse.model_validate(
        await _app_service(request).restore_app(context, application_id, body.reason)
    )


# ── API Keys ──────────────────────────────────────────────────────────────────


@router.get(
    "/applications/{application_id}/api_keys",
    response_model=ApiKeyPage,
    operation_id="list_api_keys",
)
async def list_api_keys(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("list_api_keys")],
    application_id: UUID,
    cursor: str | None = Query(default=None),
    status: Annotated[ApiKeyStatus, Query()] = ApiKeyStatus.ACTIVE,
) -> ApiKeyPage:
    query = f"api_keys:{application_id}:{status.value}"
    items, position = await _key_service(request).list_keys(
        context,
        application_id,
        cursor=_decode_cursor(cursor, context, query=query),
        status=status,
    )
    return ApiKeyPage.model_validate(
        _page(items, position, context, query=query)
    )


@router.post(
    "/applications/{application_id}/api_keys",
    status_code=201,
    response_model=ApiKeyIssuedResponse,
    operation_id="create_api_key",
)
async def create_api_key(
    request: Request,
    body: ApiKeyCreate,
    context: Annotated[PrincipalContext, management_permission("create_api_key")],
    application_id: UUID,
) -> ApiKeyIssuedResponse:
    return ApiKeyIssuedResponse.model_validate(
        await _key_service(request).issue(context, application_id, body.scopes, body.ttl_days)
    )


@router.get("/api_keys/{api_key_id}", response_model=ApiKeyResponse, operation_id="get_api_key")
async def get_api_key(
    request: Request,
    context: Annotated[PrincipalContext, management_permission("get_api_key")],
    api_key_id: str = Path(min_length=1),
) -> ApiKeyResponse:
    return ApiKeyResponse.model_validate(await _key_service(request).get_key(context, api_key_id))


@router.get("/api_keys/{api_key_id}/secret", status_code=410, operation_id="get_api_key_secret")
async def get_api_key_secret(
    request: Request,
    _context: Annotated[PrincipalContext, management_permission("get_api_key_secret")],
    api_key_id: str = Path(min_length=1),
) -> Any:
    raise ApiError(
        "secret_not_retrievable", "API key secrets are only shown once at creation", status_code=410
    )


@router.post(
    "/api_keys/{api_key_id}/rotations",
    status_code=201,
    response_model=ApiKeyIssuedResponse,
    operation_id="rotate_api_key",
)
async def rotate_api_key(
    request: Request,
    body: ApiKeyRotate,
    context: Annotated[PrincipalContext, management_permission("rotate_api_key")],
    api_key_id: str = Path(min_length=1),
) -> ApiKeyIssuedResponse:
    return ApiKeyIssuedResponse.model_validate(
        await _key_service(request).rotate(context, api_key_id, body.overlap_seconds)
    )


@router.post(
    "/api_keys/{api_key_id}/revocations",
    response_model=ApiKeyResponse,
    operation_id="revoke_api_key",
)
async def revoke_api_key(
    request: Request,
    body: ApiKeyRevoke,
    context: Annotated[PrincipalContext, management_permission("revoke_api_key")],
    api_key_id: str = Path(min_length=1),
) -> ApiKeyResponse:
    return ApiKeyResponse.model_validate(
        await _key_service(request).revoke(context, api_key_id, body.reason)
    )
