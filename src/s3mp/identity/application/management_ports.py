"""Narrow persistence ports consumed by identity and authorization management."""

from typing import Any, Protocol
from uuid import UUID

from s3mp.identity.infrastructure.models import MembershipStatus, PrincipalType, UserStatus

Page = tuple[list[dict[str, Any]], UUID | None]


class IdentityManagementStore(Protocol):
    async def tenant_context(
        self, tenant_id: UUID, principal_id: UUID
    ) -> dict[str, Any] | None: ...
    async def tenant_memberships_for_principal(
        self, principal_id: UUID
    ) -> list[dict[str, Any]]: ...
    async def list_users(
        self,
        tenant_id: UUID,
        limit: int = 50,
        cursor: UUID | None = None,
        status: UserStatus = UserStatus.ACTIVE,
        principal_type: PrincipalType = PrincipalType.USER,
    ) -> Page: ...
    async def get_user(self, tenant_id: UUID, user_id: UUID) -> dict[str, Any] | None: ...
    async def list_members(
        self,
        tenant_id: UUID,
        limit: int = 50,
        cursor: UUID | None = None,
        status: MembershipStatus = MembershipStatus.ACTIVE,
    ) -> Page: ...
    async def create_member(
        self, tenant_id: UUID, email: str, display_name: str | None
    ) -> dict[str, Any]: ...
    async def get_member(self, tenant_id: UUID, membership_id: UUID) -> dict[str, Any] | None: ...
    async def update_member(
        self, tenant_id: UUID, membership_id: UUID, status: str, reason: str, changed_by: UUID
    ) -> dict[str, Any] | None: ...
    async def list_group_members(
        self, tenant_id: UUID, group_id: UUID, limit: int = 50, cursor: UUID | None = None
    ) -> Page | None: ...
    async def add_group_member(
        self, tenant_id: UUID, group_id: UUID, membership_id: UUID
    ) -> bool: ...
    async def remove_group_member(
        self, tenant_id: UUID, group_id: UUID, membership_id: UUID
    ) -> bool: ...


class AuthorizationManagementStore(Protocol):
    async def get_principal(self, tenant_id: UUID, principal_id: UUID) -> dict[str, Any] | None: ...
    async def list_groups(
        self, tenant_id: UUID, limit: int = 50, cursor: UUID | None = None
    ) -> Page: ...
    async def create_group(
        self, tenant_id: UUID, name: str, description: str | None, created_by: UUID
    ) -> dict[str, Any]: ...
    async def get_group(self, tenant_id: UUID, group_id: UUID) -> dict[str, Any] | None: ...
    async def update_group(
        self, tenant_id: UUID, group_id: UUID, name: str | None, description: str | None
    ) -> dict[str, Any] | None: ...
    async def delete_group(self, tenant_id: UUID, group_id: UUID) -> bool: ...
    async def list_roles(
        self, tenant_id: UUID, limit: int = 50, cursor: UUID | None = None
    ) -> Page: ...
    async def create_role(
        self, tenant_id: UUID, name: str, description: str | None, permissions: list[str]
    ) -> dict[str, Any]: ...
    async def get_role(self, tenant_id: UUID, role_id: UUID) -> dict[str, Any] | None: ...
    async def update_role(
        self,
        tenant_id: UUID,
        role_id: UUID,
        name: str | None,
        description: str | None,
        permissions: list[str] | None,
    ) -> dict[str, Any] | None: ...
    async def list_role_bindings(
        self,
        tenant_id: UUID,
        principal_id: UUID | None = None,
        limit: int = 50,
        cursor: UUID | None = None,
        storage_space_id: UUID | None = None,
    ) -> Page: ...
    async def create_role_binding(
        self,
        tenant_id: UUID,
        principal_id: UUID,
        role_id: UUID,
        effect: str,
        storage_space_id: UUID | None,
        canonical_prefix: str | None,
        reason: str,
        starts_at: Any,
        expires_at: Any,
        created_by: UUID,
    ) -> dict[str, Any] | None: ...
    async def get_role_binding(
        self, tenant_id: UUID, binding_id: UUID
    ) -> dict[str, Any] | None: ...
    async def revoke_role_binding(self, tenant_id: UUID, binding_id: UUID) -> bool: ...
    async def bindings_for_principal(
        self, tenant_id: UUID, principal_id: UUID
    ) -> list[dict[str, Any]]: ...
    async def bindings_for_role(self, tenant_id: UUID, role_id: UUID) -> list[dict[str, Any]]: ...
    async def record_security_audit(
        self,
        tenant_id: UUID,
        actor_principal_id: UUID,
        action: str,
        resource_type: str,
        resource_id: str | None,
        details: dict[str, object],
    ) -> None: ...
    async def storage_space_exists(self, tenant_id: UUID, storage_space_id: UUID) -> bool: ...
