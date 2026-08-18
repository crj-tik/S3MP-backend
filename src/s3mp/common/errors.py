"""Stable API error types and handlers."""

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def _body(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request.state.request_id,
    }
    if details is not None:
        body["details"] = jsonable_encoder(details)
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(request, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"pointer": "/" + "/".join(str(part) for part in error["loc"]), "reason": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_body(request, "validation_failed", "Request validation failed", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "resource_not_found", 405: "method_not_allowed"}
        code = codes.get(exc.status_code, "http_error")
        message = "Resource not found" if exc.status_code == 404 else str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content=_body(request, code, message))

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        # Keep the public response generic, but retain the request id and full
        # traceback in server logs so production 500s are diagnosable.
        logger.exception(
            "Unhandled API exception request_id=%s method=%s path=%s",
            request.state.request_id,
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content=_body(request, "internal_error", "An internal error occurred"),
        )
