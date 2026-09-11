"""HTTP boundary for global browser account authentication."""

import logging
from typing import Annotated
from urllib.parse import parse_qs
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import RedirectResponse

from s3mp.common.api.dependencies import application_service
from s3mp.common.errors import ApiError
from s3mp.common.logging import log_event
from s3mp.platform.application.account_authentication import AccountAuthenticationService
from s3mp.platform.application.cas_authentication import CasAuthentication, CasAuthenticationError
from s3mp.platform.domain.context import PlatformContext

router = APIRouter(prefix="/api/v1/auth", tags=["Account authentication"])
registration_router = APIRouter(prefix="/api/v1/account", tags=["Platform account"])
account_service = application_service("account_authentication")
logger = logging.getLogger(__name__)


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


class Account(_Strict):
    id: str
    email: str
    employee_number: str | None = None
    display_name: str


class AccountTenantSummary(_Strict):
    id: str
    name: str
    slug: str
    membership_id: str
    membership_status: str


class AccountContext(_Strict):
    account: Account
    tenants: list[AccountTenantSummary]
    platform_permissions: list[str] = Field(default_factory=list)


class LogoutResponse(_Strict):
    cas_logout_url: str | None = None


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


def _clear_tenant_cookies(response: Response, request: Request) -> None:
    secure = request.app.state.settings.secure_browser_cookies
    response.delete_cookie("s3mp_session", path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie("s3mp_csrf", path="/", secure=secure, httponly=False, samesite="lax")


def _cas_authentication(request: Request) -> CasAuthentication:
    service = getattr(request.app.state, "cas_authentication", None)
    if not isinstance(service, CasAuthentication):
        raise ApiError(
            "authentication_unavailable", "CAS authentication is not enabled", status_code=404
        )
    return service


@router.get("/cas/login", include_in_schema=True, operation_id="cas_login")
async def cas_login(request: Request, return_to: str | None = Query(default=None)) -> Response:
    try:
        url, state = await _cas_authentication(request).begin(return_to)
    except CasAuthenticationError as exc:
        raise ApiError(
            "validation_failed", "Invalid login return destination", status_code=422
        ) from exc
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        "s3mp_cas_state",
        state,
        max_age=request.app.state.settings.cas_state_ttl_seconds,
        httponly=True,
        secure=request.app.state.settings.secure_browser_cookies,
        samesite="lax",
        path="/api/v1/auth/cas/callback",
    )
    return response


@router.get("/cas/callback", include_in_schema=True, operation_id="cas_callback")
async def cas_callback(
    request: Request,
    service: Annotated[AccountAuthenticationService, account_service],
    ticket: str | None = Query(default=None, min_length=1),
) -> Response:
    state = request.cookies.get("s3mp_cas_state")
    if not ticket or not state:
        log_event(
            logger,
            logging.WARNING,
            "cas_callback_failed",
            layer="authentication",
            dependency="browser_state",
            dependency_operation="callback_state_validation",
            outcome="failed",
            error_code="missing_ticket_or_state",
        )
        raise ApiError("authentication_failed", "Authentication failed", status_code=401)
    try:
        cas = _cas_authentication(request)
        return_to = await cas.consume(state)
        identity = await cas.verify(ticket)
    except CasAuthenticationError as exc:
        log_event(
            logger,
            logging.WARNING,
            "cas_callback_failed",
            layer="authentication",
            dependency="cas_session_authentication",
            dependency_operation=exc.stage,
            outcome="failed",
            error_code=exc.error_code,
            error_type=exc.error_type,
            error_detail=exc.error_detail,
            status_code=exc.status_code,
        )
        raise ApiError("authentication_failed", "Authentication failed", status_code=401) from exc
    if request.app.state.settings.cas_log_identity_details:
        log_event(
            logger,
            logging.INFO,
            "cas_identity_verified",
            layer="authentication",
            dependency="session_identity_verification",
            dependency_operation="identity_attribute_diagnostics",
            outcome="succeeded",
            identity_details=identity.debug_fields,
        )
    try:
        result, session_token, csrf_token = await service.login_external(
            issuer=request.app.state.settings.cas_issuer or "",
            subject=identity.subject,
            employee_number=identity.employee_number,
            email=identity.email,
            display_name=identity.display_name,
            service_ticket=ticket,
        )
    except ApiError as exc:
        log_event(
            logger,
            logging.WARNING,
            "cas_callback_failed",
            layer="authentication",
            dependency="s3mp_account_linking",
            dependency_operation="external_identity_resolution",
            outcome="failed",
            error_code=exc.code,
            error_type=type(exc).__name__,
            error_detail=exc.message,
        )
        raise
    del result
    response = RedirectResponse(url=return_to, status_code=302)
    response.delete_cookie(
        "s3mp_cas_state",
        path="/api/v1/auth/cas/callback",
        secure=request.app.state.settings.secure_browser_cookies,
        httponly=True,
        samesite="lax",
    )
    _clear_tenant_cookies(response, request)
    _set_account_cookies(response, request, session_token, csrf_token)
    return response


@router.post("/login", response_model=AccountContext, operation_id="account_login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AccountAuthenticationService, account_service],
) -> AccountContext:
    if request.app.state.settings.environment.lower() == "production":
        raise ApiError("password_login_disabled", "Password login is disabled", status_code=403)
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
    _clear_tenant_cookies(response, request)
    _set_account_cookies(response, request, session_token, csrf_token)
    return AccountContext.model_validate(result)


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


@router.get("/me", response_model=AccountContext, operation_id="get_account_context")
async def me(
    context: Annotated[PlatformContext, Depends(account_context)],
    service: Annotated[AccountAuthenticationService, account_service],
) -> AccountContext:
    return AccountContext.model_validate(await service.account_context(context))


@router.post(
    "/tenant-invitations/{membership_id}/accept",
    response_model=AccountContext,
    operation_id="accept_tenant_invitation",
)
async def accept_tenant_invitation(
    membership_id: UUID,
    context: Annotated[PlatformContext, Depends(account_context)],
    service: Annotated[AccountAuthenticationService, account_service],
    _csrf: Annotated[str | None, Header(alias="X-S3MP-CSRF")] = None,
) -> AccountContext:
    return AccountContext.model_validate(
        await service.accept_tenant_invitation(context, membership_id)
    )


@router.post("/logout", operation_id="account_logout")
async def logout(
    request: Request,
    context: Annotated[PlatformContext, Depends(account_context)],
    service: Annotated[AccountAuthenticationService, account_service],
    _csrf: Annotated[str | None, Header(alias="X-S3MP-CSRF")] = None,
) -> Response:
    await service.logout(context)
    secure = request.app.state.settings.secure_browser_cookies
    cas = getattr(request.app.state, "cas_authentication", None)
    cas_logout_url = cas.global_logout_url() if isinstance(cas, CasAuthentication) else None
    result = RedirectResponse(
        url=cas_logout_url or "/login?cas_logged_out=1",
        status_code=302,
    )
    result.delete_cookie(
        "s3mp_account_session", path="/", secure=secure, httponly=True, samesite="lax"
    )
    result.delete_cookie(
        "s3mp_account_csrf", path="/", secure=secure, httponly=False, samesite="lax"
    )
    _clear_tenant_cookies(result, request)
    return result


@router.post("/cas/callback", status_code=200, operation_id="cas_single_logout")
async def cas_single_logout(
    request: Request,
    service: Annotated[AccountAuthenticationService, account_service],
) -> Response:
    """Receive a CAS server-initiated SLO callback on the configured service URL."""
    content_type = request.headers.get("content-type", "").lower()
    if not content_type.startswith("application/x-www-form-urlencoded"):
        raise ApiError("validation_failed", "Invalid CAS logout request", status_code=422)
    try:
        body = (await request.body()).decode("utf-8")
        logout_request = parse_qs(body, keep_blank_values=True).get("logoutRequest", [""])[0]
        ticket = CasAuthentication.logout_request_ticket(logout_request)
    except (UnicodeDecodeError, CasAuthenticationError) as exc:
        log_event(
            logger,
            logging.WARNING,
            "cas_single_logout_rejected",
            layer="authentication",
            dependency="cas",
            dependency_operation="single_logout_callback",
            outcome="failed",
            error_code="invalid_logout_request",
        )
        raise ApiError("validation_failed", "Invalid CAS logout request", status_code=422) from exc
    await service.logout_cas_service_ticket(ticket)
    log_event(
        logger,
        logging.INFO,
        "cas_single_logout_processed",
        layer="authentication",
        dependency="cas",
        dependency_operation="single_logout_callback",
        outcome="succeeded",
    )
    return Response(status_code=200)


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
