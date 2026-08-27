"""HTTP request context and completion logging middleware."""

import logging
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from s3mp.common.logging import bind_log_context, log_event, reset_log_context

request_id_context: ContextVar[str] = ContextVar("request_id", default="")


def current_request_id() -> str:
    """Return the request identifier for the active ASGI task, if any."""
    return request_id_context.get()


class RequestIDMiddleware:
    """Attach correlation context, response ID, and one request completion event."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._logger = logging.getLogger(__name__)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)
        log_token = bind_log_context(request_id=request_id)
        started_at = perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            route = scope.get("route")
            operation = getattr(route, "operation_id", None) or getattr(route, "path", None)
            log_event(
                self._logger,
                logging.INFO,
                "http.request.completed",
                layer="middleware",
                method=scope.get("method"),
                operation=str(operation or "unknown_operation"),
                status_code=status_code,
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
                outcome="succeeded" if status_code < 400 else "failed",
            )
            reset_log_context(log_token)
            request_id_context.reset(token)
