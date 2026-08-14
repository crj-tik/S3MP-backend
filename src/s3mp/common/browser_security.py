"""Browser-only CSRF enforcement for opaque account and tenant session cookies."""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_EXEMPT_PATHS = frozenset({"/api/v1/auth/login"})
ACCOUNT_CSRF_PREFIXES = ("/api/v1/auth/", "/api/v1/platform/", "/api/v1/account/")


def _csrf_cookie_name(path: str, *, has_tenant_session: bool) -> str | None:
    """Choose the double-submit cookie from the endpoint's security domain."""
    if path.startswith(ACCOUNT_CSRF_PREFIXES):
        return "s3mp_account_csrf"
    if has_tenant_session:
        return "s3mp_csrf"
    return None


class BrowserCSRFMiddleware(BaseHTTPMiddleware):
    """Require same-origin double-submit CSRF proof for cookie-authenticated mutations."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in UNSAFE_METHODS or request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)
        account_session = request.cookies.get("s3mp_account_session")
        tenant_session = request.cookies.get("s3mp_session")
        cookie_name = _csrf_cookie_name(
            request.url.path,
            has_tenant_session=bool(tenant_session),
        )
        if cookie_name is None and not account_session and not tenant_session:
            return await call_next(request)
        cookie = request.cookies.get(cookie_name or "s3mp_account_csrf", "")
        header = request.headers.get("X-S3MP-CSRF", "")
        token_service = getattr(request.app.state, "session_token_service", None)
        if token_service is None or not token_service.verify_csrf(cookie, header):
            return JSONResponse(
                status_code=403,
                content={
                    "code": "csrf_validation_failed",
                    "message": "CSRF validation failed",
                    "request_id": getattr(request.state, "request_id", "unknown"),
                },
            )
        return await call_next(request)
