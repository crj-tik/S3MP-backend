"""Non-blocking, API-Key-only HTTP usage observation."""

import asyncio
import logging
from datetime import UTC, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from s3mp.common.logging import log_event

logger = logging.getLogger(__name__)
API_USAGE_STREAM = "s3mp:api-usage:events"


class ApiUsageObservationMiddleware:
    """Observe final status at the HTTP boundary without reading payloads."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status_code = 500

        async def observe_send(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, observe_send)
        finally:
            state = scope.get("state", {})
            context = state.get("principal_context")
            if context is not None and getattr(context, "api_key_id", None) is not None:
                redis = getattr(scope.get("app").state, "redis", None) if scope.get("app") else None
                if redis is None:
                    log_event(
                        logger,
                        logging.WARNING,
                        "api_usage_observation.dropped",
                        layer="middleware",
                        dependency="redis",
                        dependency_operation="stream_publish",
                        outcome="failed",
                    )
                else:
                    route = scope.get("route")
                    operation = getattr(route, "operation_id", None) or getattr(route, "path", None)
                    event = {
                        "tenant_id": str(context.tenant_id),
                        "application_id": str(context.application_id),
                        "operation": str(operation or "unknown_operation"),
                        "status_code": str(status_code),
                        "request_id": str(state.get("request_id", "unknown")),
                        "occurred_at": datetime.now(UTC).isoformat(),
                    }
                    task = asyncio.create_task(self._publish(redis, event))
                    task.add_done_callback(self._log_failure)

    @staticmethod
    async def _publish(redis: object, event: dict[str, str]) -> None:
        await redis.xadd(API_USAGE_STREAM, event, maxlen=100_000, approximate=True)

    @staticmethod
    def _log_failure(task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except Exception:
            logger.exception(
                "api_usage_observation_delivery_failed",
                extra={
                    "event": "api_usage_observation.delivery_failed",
                    "layer": "infrastructure",
                    "dependency": "redis",
                    "dependency_operation": "stream_publish",
                    "outcome": "failed",
                },
            )
