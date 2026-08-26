"""Normalize JSON timestamp inputs to S3MP's business time zone."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from s3mp.common.timezone import to_china_time

_TIMESTAMP_KEYS = {"timestamp"}


def _normalize_times(value: Any, key: str | None = None) -> Any:
    if isinstance(value, str) and key and (key.endswith("_at") or key in _TIMESTAMP_KEYS):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return to_china_time(parsed).isoformat() if parsed.tzinfo is not None else value
    if isinstance(value, dict):
        return {
            child_key: _normalize_times(child_value, child_key)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_normalize_times(item, key) for item in value]
    return value


class ChinaTimeInputMiddleware:
    """Convert timezone-aware JSON request timestamps before FastAPI validation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_type = dict(scope["headers"]).get(b"content-type", b"")
        if b"application/json" not in content_type:
            await self.app(scope, receive, send)
            return

        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                await self.app(scope, receive, send)
                return
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        try:
            normalized = _normalize_times(json.loads(body))
            body = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass

        delivered = False

        async def normalized_receive() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, normalized_receive, send)
