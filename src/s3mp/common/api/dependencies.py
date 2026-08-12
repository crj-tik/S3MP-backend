"""Shared FastAPI dependencies for tenant context, service wiring, and error conversion."""

from typing import Any

from fastapi import Depends, Request

from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext


def principal_context(request: Request) -> PrincipalContext:
    """Extract the server-derived PrincipalContext from request state.

    Every authenticated endpoint must call this; it fails with 401 when the
    auth middleware has not populated a valid context.
    """
    context = getattr(request.state, "principal_context", None)
    if not isinstance(context, PrincipalContext):
        raise ApiError("authentication_required", "Authentication required", status_code=401)
    return context


def application_service(attr: str) -> Any:
    """Return a FastAPI dependency that resolves an application service from app.state.

    Usage:
        router = APIRouter()
        identity_svc = application_service("identity_management")

        @router.get("/users")
        async def list_users(request: Request, svc=Depends(identity_svc)):
            return await svc.list_users(principal_context(request))
    """

    def resolver(request: Request) -> Any:
        service = getattr(request.app.state, attr, None)
        if service is None:
            raise ApiError(
                "internal_error",
                f"Application service '{attr}' is not configured",
                status_code=500,
            )
        return service

    return Depends(resolver)