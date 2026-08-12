"""Liveness and dependency readiness endpoints."""

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

Check = Callable[[], Awaitable[None]]
router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", response_model=None)
async def ready(request: Request) -> dict[str, object] | JSONResponse:
    checks: dict[str, Check] = request.app.state.readiness_checks
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            async with asyncio.timeout(request.app.state.readiness_timeout):
                await check()
            results[name] = "ok"
        except (TimeoutError, OSError, RuntimeError, SQLAlchemyError, RedisError):
            results[name] = "unavailable"
    ready_now = all(result == "ok" for result in results.values())
    body: dict[str, object] = {"status": "ok" if ready_now else "unavailable", "checks": results}
    if ready_now:
        return body
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body)
