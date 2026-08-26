"""统一 API 时间输出格式。

数据库继续使用带时区的 datetime 类型；仅在 JSON 出站边界格式化，避免丢失
时区、精度和数据库的时间排序能力。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from s3mp.common.timezone import to_china_time

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_datetime(value: datetime | None) -> str | None:
    return to_china_time(value).strftime(DATETIME_FORMAT) if value is not None else None


def _format_json_times(value: Any, key: str | None = None) -> Any:
    if isinstance(value, str) and key and (key.endswith("_at") or key in {"timestamp"}):
        try:
            return format_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return value
    if isinstance(value, dict):
        return {k: _format_json_times(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_format_json_times(item, key) for item in value]
    return value


def _rebuilt_response(response: Response, body: bytes) -> Response:
    """Replace a consumed JSON body without collapsing repeated response headers.

    ``Set-Cookie`` is deliberately allowed to appear multiple times. Converting
    ``response.headers`` to a dict loses every value except one, which in turn
    prevents the browser from receiving the account session and CSRF cookies.
    """
    rebuilt = Response(content=body, status_code=response.status_code)
    rebuilt.raw_headers = [
        (name, value)
        for name, value in response.raw_headers
        if name.lower() != b"content-length"
    ]
    return rebuilt


class DateTimeFormatMiddleware(BaseHTTPMiddleware):
    """将 JSON 响应中的时间字段统一为 ``yyyy-MM-dd HH:mm:ss``。"""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            payload = _format_json_times(json.loads(body))
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _rebuilt_response(response, body)

        return _rebuilt_response(response, body)
