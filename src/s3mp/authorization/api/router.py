"""Authorization management HTTP surface; business rules live in the application service."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext

router = APIRouter(prefix="/api/v1", tags=["Authorization"])


class GroupWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class RoleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    permissions: list[str] = Field(default_factory=list)


class ResourceScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    storage_space_id: str | None = None
    canonical_prefix: str | None = None


class RoleBindingWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str
    role_id: str
    effect: str
    scope: ResourceScope
    reason: str = Field(min_length=1, max_length=500)
    starts_at: datetime | None = None
    expires_at: datetime


def _context(request: Request) -> PrincipalContext:
    context = getattr(request.state, "principal_context", None)
    if not isinstance(context, PrincipalContext):
        raise ApiError("authentication_required", "Authentication required", status_code=401)
    return context


def _service(request: Request) -> Any:
    service = getattr(request.app.state, "authorization_management", None)
    if service is None:
        raise ApiError(
            "internal_error", "Authorization management is not configured", status_code=500
        )
    return service


@router.get("/groups", operation_id="list_groups")
async def list_groups(request: Request) -> Any:
    return await _service(request).list_groups(_context(request))


@router.post("/groups", status_code=201, operation_id="create_group")
async def create_group(request: Request, body: GroupWrite) -> Any:
    return await _service(request).create_group(_context(request), body)


@router.get("/groups/{group_id}", operation_id="get_group")
async def get_group(request: Request, group_id: str = Path(min_length=1)) -> Any:
    return await _service(request).get_group(_context(request), group_id)


@router.patch("/groups/{group_id}", operation_id="update_group")
async def update_group(
    request: Request, body: GroupWrite, group_id: str = Path(min_length=1)
) -> Any:
    return await _service(request).update_group(_context(request), group_id, body)


@router.delete("/groups/{group_id}", status_code=204, operation_id="delete_group")
async def delete_group(request: Request, group_id: str = Path(min_length=1)) -> None:
    await _service(request).delete_group(_context(request), group_id)


@router.get("/roles", operation_id="list_roles")
async def list_roles(request: Request) -> Any:
    return await _service(request).list_roles(_context(request))


@router.post("/roles", status_code=201, operation_id="create_role")
async def create_role(request: Request, body: RoleWrite) -> Any:
    return await _service(request).create_role(_context(request), body)


@router.get("/roles/{role_id}", operation_id="get_role")
async def get_role(request: Request, role_id: str = Path(min_length=1)) -> Any:
    return await _service(request).get_role(_context(request), role_id)


@router.patch("/roles/{role_id}", operation_id="update_role")
async def update_role(request: Request, body: RoleWrite, role_id: str = Path(min_length=1)) -> Any:
    return await _service(request).update_role(_context(request), role_id, body)


@router.get("/role_bindings", operation_id="list_role_bindings")
async def list_role_bindings(request: Request, principal_id: str | None = None) -> Any:
    return await _service(request).list_role_bindings(_context(request), principal_id)


@router.post("/role_bindings", status_code=201, operation_id="create_role_binding")
async def create_role_binding(request: Request, body: RoleBindingWrite) -> Any:
    return await _service(request).create_role_binding(_context(request), body)


@router.get("/role_bindings/{role_binding_id}", operation_id="get_role_binding")
async def get_role_binding(request: Request, role_binding_id: str = Path(min_length=1)) -> Any:
    return await _service(request).get_role_binding(_context(request), role_binding_id)


@router.delete(
    "/role_bindings/{role_binding_id}", status_code=204, operation_id="revoke_role_binding"
)
async def revoke_role_binding(request: Request, role_binding_id: str = Path(min_length=1)) -> None:
    await _service(request).revoke_role_binding(_context(request), role_binding_id)


# ── Effective permissions & simulation ────────────────────────────────────────


@router.get(
    "/principals/{principal_id}/effective_permissions", operation_id="get_effective_permissions"
)
async def get_effective_permissions(
    request: Request,
    principal_id: str = Path(min_length=1),
    storage_space_id: str | None = None,
    object_key: str | None = None,
) -> Any:
    return await _service(request).get_effective_permissions(
        _context(request), principal_id, storage_space_id, object_key
    )


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str
    permission: str
    storage_space_id: str | None = None
    object_key: str | None = None


@router.post("/authorization/simulations", operation_id="simulate_authorization")
async def simulate_authorization(request: Request, body: SimulationRequest) -> Any:
    return await _service(request).simulate_authorization(
        _context(request), body.principal_id, body.permission,
        body.storage_space_id, body.object_key,
    )
