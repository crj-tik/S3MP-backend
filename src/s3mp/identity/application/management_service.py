"""Application service for tenant-scoped identity management."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from s3mp.authorization.application.management_service import AuthorizationManagementService
from s3mp.common.errors import ApiError
from s3mp.identity.application.management_ports import IdentityManagementStore
from s3mp.identity.domain.context import PrincipalContext


@dataclass(slots=True)
class IdentityManagementService:
    store: IdentityManagementStore
    authorization: AuthorizationManagementService

    async def get_me(self, context: PrincipalContext) -> dict[str, Any]:
        current = await self.store.tenant_context(context.tenant_id, context.principal_id)
        if current is None:
            raise ApiError("authentication_required", "Authentication required", status_code=401)
        permissions = await self.authorization.get_effective_permissions(
            context, context.principal_id
        )
        return {
            "principal": {
                key: value
                for key, value in current["principal"].items()
                if key in {"id", "type", "display_name"}
            },
            "current_tenant": current["current_tenant"],
            "available_tenants": await self.store.tenant_memberships_for_principal(
                context.principal_id
            ),
            "coarse_permissions": [
                item["permission"]
                for item in permissions["permissions"]
                if item["decision"] == "allow"
            ],
            "authorization_version": current["authorization_version"],
        }

    async def list_users(
        self, context: PrincipalContext, **page: Any
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        return await self.store.list_users(context.tenant_id, **page)

    async def get_user(self, context: PrincipalContext, user_id: UUID) -> dict[str, Any]:
        return _found(await self.store.get_user(context.tenant_id, user_id), "User")

    async def list_members(
        self, context: PrincipalContext, **page: Any
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        return await self.store.list_members(context.tenant_id, **page)

    async def create_member(self, context: PrincipalContext, body: Any) -> dict[str, Any]:
        try:
            return await self.store.create_member(context.tenant_id, body.email, body.display_name)
        except ValueError as exc:
            raise ApiError(
                "duplicate_resource", "Membership already exists", status_code=409
            ) from exc

    async def get_member(self, context: PrincipalContext, membership_id: UUID) -> dict[str, Any]:
        return _found(await self.store.get_member(context.tenant_id, membership_id), "Member")

    async def update_member(
        self, context: PrincipalContext, membership_id: UUID, body: Any
    ) -> dict[str, Any]:
        try:
            result = await self.store.update_member(
                context.tenant_id, membership_id, body.status, body.reason, context.principal_id
            )
        except ValueError as exc:
            raise ApiError(
                "validation_failed", "Invalid membership status", status_code=422
            ) from exc
        return _found(result, "Member")

    async def list_group_members(
        self, context: PrincipalContext, group_id: UUID, **page: Any
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        result = await self.store.list_group_members(context.tenant_id, group_id, **page)
        if result is None:
            raise ApiError("resource_not_found", "Group not found", status_code=404)
        return result

    async def add_group_member(
        self, context: PrincipalContext, group_id: UUID, membership_id: UUID
    ) -> None:
        try:
            result = await self.store.add_group_member(context.tenant_id, group_id, membership_id)
        except ValueError as exc:
            raise ApiError(
                "duplicate_resource", "Group membership already exists", status_code=409
            ) from exc
        if not result:
            raise ApiError("resource_not_found", "Group or member not found", status_code=404)

    async def remove_group_member(
        self, context: PrincipalContext, group_id: UUID, membership_id: UUID
    ) -> None:
        if not await self.store.remove_group_member(context.tenant_id, group_id, membership_id):
            raise ApiError("resource_not_found", "Group membership not found", status_code=404)


def _found(value: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if value is None:
        raise ApiError("resource_not_found", f"{label} not found", status_code=404)
    return value
