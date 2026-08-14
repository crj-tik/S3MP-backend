"""HTTP boundary for global browser account authentication."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.api.dependencies import application_service
from s3mp.common.errors import ApiError
from s3mp.platform.application.account_authentication import AccountAuthenticationService
from s3mp.platform.domain.context import PlatformContext

router = APIRouter(prefix="/api/v1/auth", tags=["Account authentication"])
registration_router = APIRouter(prefix="/api/v1/account", tags=["Platform account"])
account_service = application_service("account_authentication")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(_Strict):
    identifier: str | None = Field(default=None, min_length=2, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    email: str | None = Field(default=None, min_length=3, max_length=320, deprecated=True)


class RegisterRequest(_Strict):
    email: str = Field(min_length=3, max_length=320, json_schema_extra={"format": "email"})
    employee_number: str = Field(
        min_length=2, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$"
    )
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=1024)


class TenantSessionRequest(_Strict):
    tenant_id: UUID


def account_context(request: Request) -> PlatformContext:
    context = getattr(request.state, "platform_context", None)
    if not isinstance(context, PlatformContext):
        raise ApiError("authentication_required", "Authentication required", status_code=401)
    return context


def _set_account_cookies(
    response: Response, request: Request, session_token: str, csrf_token: str
) -> None:
    secure = request.app.state.settings.secure_browser_cookies
    max_age = request.app.state.settings.browser_session_ttl_seconds
    response.set_cookie(
        "s3mp_account_session",
        session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        "s3mp_account_csrf",
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", operation_id="account_login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AccountAuthenticationService, account_service],
) -> object:
    client = request.client.host if request.client else "unknown"
    identifier = body.identifier
    if body.email is not None:
        if body.identifier is not None and body.identifier != body.email:
            raise ApiError("validation_failed", "Conflicting login identifiers", status_code=422)
        identifier = body.email
    if identifier is None:
        raise ApiError("validation_failed", "Login identifier is required", status_code=422)
    result, session_token, csrf_token = await service.login(
        identifier,
        body.password,
        rate_limit_key=f"account-login:{client}:{identifier.strip().casefold()}",
    )
    _set_account_cookies(response, request, session_token, csrf_token)
    return result


@registration_router.post("/register", status_code=201, operation_id="register_account")
async def register(
    body: RegisterRequest,
    service: Annotated[AccountAuthenticationService, account_service],
) -> object:
    return await service.register(
        email=body.email,
        employee_number=body.employee_number,
        display_name=body.display_name,
        password=body.password,
    )


@router.get("/me", operation_id="get_account_context")
async def me(
    context: Annotated[PlatformContext, Depends(account_context)],
    service: Annotated[AccountAuthenticationService, account_service],
) -> object:
    return await service.account_context(context)


@router.post("/logout", status_code=204, operation_id="account_logout")
async def logout(
    request: Request,
    response: Response,
    context: Annotated[PlatformContext, Depends(account_context)],
    service: Annotated[AccountAuthenticationService, account_service],
    _csrf: Annotated[str | None, Header(alias="X-S3MP-CSRF")] = None,
) -> None:
    await service.logout(context)
    secure = request.app.state.settings.secure_browser_cookies
    response.delete_cookie(
        "s3mp_account_session", path="/", secure=secure, httponly=True, samesite="lax"
    )
    response.delete_cookie(
        "s3mp_account_csrf", path="/", secure=secure, httponly=False, samesite="lax"
    )


@router.post("/tenant-sessions", status_code=204, operation_id="select_tenant_session")
async def select_tenant_session(
    body: TenantSessionRequest,
    request: Request,
    response: Response,
    context: Annotated[PlatformContext, Depends(account_context)],
    service: Annotated[AccountAuthenticationService, account_service],
    _csrf: Annotated[str | None, Header(alias="X-S3MP-CSRF")] = None,
) -> None:
    session_token, csrf_token = await service.select_tenant(context, body.tenant_id)
    secure = request.app.state.settings.secure_browser_cookies
    max_age = request.app.state.settings.browser_session_ttl_seconds
    response.set_cookie(
        "s3mp_session",
        session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        "s3mp_csrf",
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )
