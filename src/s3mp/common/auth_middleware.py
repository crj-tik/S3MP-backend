"""Authentication middleware: resolve credentials to PrincipalContext."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/health/live",
        "/health/ready",
        "/openapi.json",
        "/docs",
        "/redoc",
        "/docs/oauth2-redirect",
        "/api/v1/auth/login",
        "/api/v1/account/register",
    }
)

# Skip auth when the test harness has already injected a principal_context
SKIP_AUTH_HEADER = "X-S3MP-Test-Auth-Bypass"


class AuthMiddleware(BaseHTTPMiddleware):
    """Resolve session or API key credentials to PrincipalContext on request.state."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        # Allow test harness to pre-inject context (test middleware runs before us)
        if hasattr(request.state, "principal_context"):
            return await call_next(request)

        try:
            await _resolve_available_contexts(request)
        except ApiError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": getattr(request.state, "request_id", "unknown"),
                },
            )
        return await call_next(request)


async def _resolve_available_contexts(request: Request) -> None:
    """Resolve every supplied credential into its own, non-interchangeable context."""
    account_token = request.cookies.get("s3mp_account_session")
    if account_token:
        store = getattr(request.app.state, "platform_store", None)
        session_svc = getattr(request.app.state, "session_token_service", None)
        if store is None or session_svc is None:
            raise ApiError(
                "internal_error", "Account authentication is not configured", status_code=500
            )
        account_context = await store.resolve_account_session(session_svc.digest(account_token))
        if account_context is None:
            raise ApiError(
                "authentication_required", "Account session is not active", status_code=401
            )
        request.state.platform_context = account_context

    session_token = request.cookies.get("s3mp_session")
    if session_token:
        request.state.principal_context = await _resolve_session(request, session_token)
        return

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("S3MP-Key "):
        request.state.principal_context = await _resolve_api_key(request, auth_header)


async def _resolve_session(request: Request, token: str) -> PrincipalContext:
    """Resolve session cookie to PrincipalContext."""
    provider = getattr(request.app.state, "identity_context_provider", None)
    if provider is None:
        raise ApiError("internal_error", "Identity provider not configured", status_code=500)
    session_svc = getattr(request.app.state, "session_token_service", None)
    if session_svc is None:
        raise ApiError("internal_error", "Session token service not configured", status_code=500)
    digest = session_svc.digest(token)
    return await provider.resolve_session(digest)  # type: ignore[no-any-return]


async def _resolve_api_key(request: Request, header: str) -> PrincipalContext:
    """Resolve S3MP-Key credential to PrincipalContext."""
    svc = getattr(request.app.state, "api_key_service", None)
    if svc is None:
        raise ApiError("internal_error", "API key service not configured", status_code=500)
    tenant_id, key_id, record = await svc.authenticate(header)
    return PrincipalContext.for_application(
        tenant_id=tenant_id,
        principal_id=UUID(str(record["application_principal_id"])),
        application_id=UUID(str(record["application_id"])),
        api_key_id=key_id,
        api_key_scopes=frozenset(str(scope) for scope in record.get("scopes", [])),
        authorization_version=int(record.get("application_authorization_version", 1)),
    )
