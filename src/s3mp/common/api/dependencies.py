"""Shared FastAPI dependencies for tenant context, service wiring, and error conversion."""

from typing import Any

from fastapi import Depends, Request

from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

MANAGEMENT_OPERATION_PERMISSIONS = {
    "list_users": "members.read",
    "get_user": "members.read",
    "list_members": "members.read",
    "create_member": "members.manage",
    "get_member": "members.read",
    "update_member": "members.manage",
    "list_group_members": "groups.read",
    "add_group_member": "groups.manage",
    "remove_group_member": "groups.manage",
    "list_groups": "groups.read",
    "create_group": "groups.manage",
    "get_group": "groups.read",
    "update_group": "groups.manage",
    "delete_group": "groups.manage",
    "list_roles": "roles.read",
    "create_role": "roles.manage",
    "get_role": "roles.read",
    "update_role": "roles.manage",
    "list_role_bindings": "role_bindings.read",
    "create_role_binding": "role_bindings.manage",
    "get_role_binding": "role_bindings.read",
    "revoke_role_binding": "role_bindings.manage",
    "get_effective_permissions": "authorization.explain",
    "simulate_authorization": "authorization.simulate",
    "list_applications": "applications.read",
    "create_application": "applications.manage",
    "get_application": "applications.read",
    "update_application": "applications.manage",
    "list_api_keys": "api_keys.read",
    "create_api_key": "api_keys.manage",
    "get_api_key": "api_keys.read",
    "get_api_key_secret": "api_keys.read",
    "rotate_api_key": "api_keys.manage",
    "revoke_api_key": "api_keys.manage",
}


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


def management_permission(operation_id: str) -> Any:
    """Require the catalog permission bound to a management operation."""
    permission = MANAGEMENT_OPERATION_PERMISSIONS[operation_id]

    async def resolver(request: Request) -> PrincipalContext:
        context = principal_context(request)
        service = getattr(request.app.state, "authorization_management", None)
        if service is None:
            raise ApiError(
                "internal_error", "Authorization management is not configured", status_code=500
            )
        await service.require_permission(context, permission)
        return context

    return Depends(resolver)
