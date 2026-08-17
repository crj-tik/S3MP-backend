"""Dependencies for routes authorized by a global account session."""

from typing import Any, cast

from fastapi import Depends, Request

from s3mp.common.errors import ApiError
from s3mp.platform.application.authorization import PlatformAuthorizer
from s3mp.platform.domain.context import PlatformContext


def platform_context(request: Request) -> PlatformContext:
    context = getattr(request.state, "platform_context", None)
    if not isinstance(context, PlatformContext):
        raise ApiError("account_authentication_required", "Account authentication required", 401)
    return context


def platform_permission(permission: str, operation_id: str | None = None) -> Any:
    def resolver(request: Request) -> PlatformContext:
        context = platform_context(request)
        PlatformAuthorizer().require(context, permission)
        return context

    annotated_resolver = cast(Any, resolver)
    if operation_id is not None:
        annotated_resolver.__s3mp_management_operation_id__ = operation_id
    annotated_resolver.__s3mp_platform_permission__ = permission
    return Depends(resolver)
