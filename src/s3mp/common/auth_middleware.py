"""Authentication middleware: resolve credentials to PrincipalContext."""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

PUBLIC_PATHS: frozenset[str] = frozenset(
    {"/health/live", "/health/ready", "/openapi.json", "/docs", "/redoc",
     "/docs/oauth2-redirect"}
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
            context = await _resolve_context(request)
            request.state.principal_context = context
        except ApiError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"code": exc.code, "message": exc.message,
                         "request_id": getattr(request.state, "request_id", "unknown")},
            )
        return await call_next(request)


async def _resolve_context(request: Request) -> PrincipalContext:
    """Resolve credentials from session cookie or S3MP-Key header."""
    # Try session cookie first
    session_token = request.cookies.get("s3mp_session")
    if session_token:
        return await _resolve_session(request, session_token)

    # Try API key header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("S3MP-Key "):
        return await _resolve_api_key(request, auth_header)

    raise ApiError("authentication_required", "Authentication required", status_code=401)


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
    context = PrincipalContext(
        tenant_id=tenant_id,
        principal_id=record["application_id"],
        membership_id=record["application_id"],
        authorization_version=record.get("authorization_version", 1),
    )
    return context