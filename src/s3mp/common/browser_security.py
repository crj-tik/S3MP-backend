"""Browser-only CSRF enforcement for opaque account and tenant session cookies."""

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_EXEMPT_PATHS = frozenset({"/api/v1/auth/login"})


class BrowserCSRFMiddleware(BaseHTTPMiddleware):
    """Require same-origin double-submit CSRF proof for cookie-authenticated mutations."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in UNSAFE_METHODS or request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)
        account_session = request.cookies.get("s3mp_account_session")
        tenant_session = request.cookies.get("s3mp_session")
        if account_session:
            cookie = request.cookies.get("s3mp_account_csrf", "")
        elif tenant_session:
            cookie = request.cookies.get("s3mp_csrf", "")
        else:
            return await call_next(request)
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
