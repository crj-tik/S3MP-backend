"""Dependencies for routes authorized by a global account session."""

from typing import Any

from fastapi import Depends, Request

from s3mp.common.errors import ApiError
from s3mp.platform.application.authorization import PlatformAuthorizer
from s3mp.platform.domain.context import PlatformContext


def platform_context(request: Request) -> PlatformContext:
    context = getattr(request.state, "platform_context", None)
    if not isinstance(context, PlatformContext):
        raise ApiError("account_authentication_required", "Account authentication required", 401)
    return context


def platform_permission(permission: str) -> Any:
    def resolver(request: Request) -> PlatformContext:
        context = platform_context(request)
        PlatformAuthorizer().require(context, permission)
        return context

    return Depends(resolver)
