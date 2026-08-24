"""Application service for tenant-scoped authorization management."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.exc import IntegrityError

from s3mp.authorization.application.explain import explain_permissions, simulate
from s3mp.authorization.domain.evaluator import (
    Binding,
    Decision,
    evaluate,
)
from s3mp.common.errors import ApiError
from s3mp.identity.application.management_ports import AuthorizationManagementStore
from s3mp.identity.domain.context import PrincipalContext
from s3mp.platform.application.baseline import TENANT_MEMBER_PERMISSIONS


@dataclass(slots=True)
class AuthorizationManagementService:
    store: AuthorizationManagementStore
    known_permissions: frozenset[str]
    delegable_permissions: frozenset[str] | None = None
    tenant_admin_permissions: frozenset[str] | None = None

    async def require_permission(self, context: PrincipalContext, permission: str) -> None:
        bindings = await self._bindings(
            context.tenant_id,
            context.principal_id,
            include_platform_tenant_admin=context.subject_kind == "human",
            include_tenant_member_baseline=context.subject_kind == "human",
        )
        if evaluate(permission, bindings).decision != Decision.ALLOW:
            raise ApiError("permission_denied", "Permission denied", status_code=403)

    async def list_groups(
        self, context: PrincipalContext, **page: Any
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        return await self.store.list_groups(context.tenant_id, **page)

    async def create_group(self, context: PrincipalContext, body: Any) -> dict[str, Any]:
        return await self.store.create_group(
            context.tenant_id, body.name, body.description, context.principal_id
        )

    async def get_group(self, context: PrincipalContext, group_id: UUID) -> dict[str, Any]:
        result = await self.store.get_group(context.tenant_id, group_id)
        return _found(result, "Group")

    async def update_group(
        self, context: PrincipalContext, group_id: UUID, body: Any
    ) -> dict[str, Any]:
        result = await self.store.update_group(
            context.tenant_id, group_id, body.name, body.description
        )
        return _found(result, "Group")

    async def delete_group(self, context: PrincipalContext, group_id: UUID) -> None:
        if not await self.store.delete_group(context.tenant_id, group_id):
            raise ApiError("resource_not_found", "Group not found", status_code=404)

    async def list_roles(
        self, context: PrincipalContext, **page: Any
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        return await self.store.list_roles(context.tenant_id, **page)

    async def create_role(self, context: PrincipalContext, body: Any) -> dict[str, Any]:
        if body.name == "tenant-admin":
            raise ApiError(
                "validation_failed",
                "tenant-admin is a platform role and cannot be created in a tenant",
                status_code=422,
            )
        tenant_admin = await self._is_platform_tenant_admin(context)
        self._validate_permissions(body.permissions)
        self._validate_delegable_permissions(
            body.permissions, allow_non_delegable=tenant_admin
        )
        await self._require_delegable_subset(
            context, body.permissions, None, None, bypass=tenant_admin
        )
        try:
            return await self.store.create_role(
                context.tenant_id, body.name, body.description, body.permissions
            )
        except IntegrityError as exc:
            raise ApiError("duplicate_resource", "Role already exists", status_code=409) from exc

    async def get_role(self, context: PrincipalContext, role_id: UUID) -> dict[str, Any]:
        return _found(await self.store.get_role(context.tenant_id, role_id), "Role")

    async def update_role(
        self, context: PrincipalContext, role_id: UUID, body: Any
    ) -> dict[str, Any]:
        if body.name == "tenant-admin":
            raise ApiError(
                "validation_failed",
                "tenant-admin is a platform role and cannot be created in a tenant",
                status_code=422,
            )
        role = await self.store.get_role(context.tenant_id, role_id)
        if role is not None and role.get("system"):
            raise ApiError("permission_denied", "Built-in roles are immutable", status_code=403)
        if body.permissions is not None:
            tenant_admin = await self._is_platform_tenant_admin(context)
            self._validate_permissions(body.permissions)
            self._validate_delegable_permissions(
                body.permissions, allow_non_delegable=tenant_admin
            )
            await self._require_delegable_subset(
                context, body.permissions, None, None, bypass=tenant_admin
            )
            if role is not None:
                added = sorted(set(body.permissions) - set(cast(list[str], role["permissions"])))
                for binding in await self.store.bindings_for_role(context.tenant_id, role_id):
                    await self._require_delegable_subset(
                        context,
                        added,
                        binding["storage_space_id"],
                        binding["canonical_prefix"],
                        bypass=tenant_admin,
                    )
        try:
            result = await self.store.update_role(
                context.tenant_id, role_id, body.name, body.description, body.permissions
            )
        except ValueError as exc:
            raise ApiError("validation_failed", str(exc), status_code=422) from exc
        return _found(result, "Role")

    async def list_role_bindings(
        self,
        context: PrincipalContext,
        principal_id: UUID | None = None,
        **page: Any,
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        if (
            principal_id is not None
            and await self.store.get_principal(context.tenant_id, principal_id) is None
        ):
            raise ApiError("resource_not_found", "Principal not found", status_code=404)
        return await self.store.list_role_bindings(context.tenant_id, principal_id, **page)

    async def create_role_binding(self, context: PrincipalContext, body: Any) -> dict[str, Any]:
        await self.validate_role_grant(context, body.role_id, body.expires_at)
        principal = await self.store.get_principal(context.tenant_id, body.principal_id)
        if principal is None:
            raise ApiError("resource_not_found", "Principal not found", status_code=404)
        if principal.get("type") not in {"user", "group"}:
            raise ApiError(
                "validation_failed",
                "Role bindings can only target tenant members or user groups",
                status_code=422,
            )
        existing_lookup = getattr(self.store, "get_active_role_binding", None)
        if existing_lookup is not None and await existing_lookup(
            context.tenant_id, body.principal_id, body.role_id
        ):
            raise ApiError(
                "duplicate_resource",
                "This member or group already has this role binding; update it instead",
                status_code=409,
            )
        try:
            result = await self.store.create_role_binding(
                context.tenant_id,
                body.principal_id,
                body.role_id,
                body.effect,
                None,
                None,
                body.reason,
                body.starts_at,
                body.expires_at,
                context.principal_id,
            )
        except IntegrityError as exc:
            raise ApiError(
                "duplicate_resource",
                "This member or group already has this role binding; update it instead",
                status_code=409,
            ) from exc
        return _found(result, "Role binding")

    async def update_role_binding(
        self, context: PrincipalContext, binding_id: UUID, body: Any
    ) -> dict[str, Any]:
        current = await self.store.get_role_binding(context.tenant_id, binding_id)
        if current is None:
            raise ApiError("resource_not_found", "Role binding not found", status_code=404)
        await self.validate_role_grant(context, body.role_id, body.expires_at)
        result = await self.store.update_role_binding(
            context.tenant_id,
            binding_id,
            body.role_id,
            body.effect,
            body.reason,
            body.starts_at,
            body.expires_at,
        )
        return _found(result, "Role binding")

    async def validate_role_grant(
        self, context: PrincipalContext, role_id: UUID, expires_at: datetime
    ) -> None:
        """Validate a role delegation shared by bindings and member invitations."""
        tenant_admin = await self._is_platform_tenant_admin(context)
        role = await self.store.get_role(context.tenant_id, role_id)
        if role is None:
            raise ApiError("resource_not_found", "Role not found", status_code=404)
        if role.get("name") == "tenant-admin":
            raise ApiError(
                "validation_failed",
                "tenant-admin is a platform role and cannot be bound as a tenant role",
                status_code=422,
            )
        self._validate_delegable_permissions(
            role["permissions"], allow_non_delegable=tenant_admin
        )
        await self._require_delegable_subset(
            context, role["permissions"], None, None, bypass=tenant_admin
        )
        if expires_at <= datetime.now(UTC):
            raise ApiError("validation_failed", "expires_at must be in the future", status_code=422)
        await self._require_delegation_expiry_bound(
            context, role["permissions"], None, None, expires_at
        )

    async def maximum_role_grant_expiry(
        self, context: PrincipalContext, role_id: UUID
    ) -> datetime:
        """Return the latest safe expiry for an invited member's initial role."""
        tenant_admin = await self._is_platform_tenant_admin(context)
        role = await self.store.get_role(context.tenant_id, role_id)
        if role is None:
            raise ApiError("resource_not_found", "Role not found", status_code=404)
        if role.get("name") == "tenant-admin":
            raise ApiError(
                "validation_failed",
                "tenant-admin is a platform role and cannot be bound as a tenant role",
                status_code=422,
            )
        self._validate_delegable_permissions(
            role["permissions"], allow_non_delegable=tenant_admin
        )
        await self._require_delegable_subset(
            context, role["permissions"], None, None, bypass=tenant_admin
        )
        bindings = await self._bindings(
            context.tenant_id,
            context.principal_id,
            include_tenant_member_baseline=context.subject_kind == "human",
        )
        per_permission_expiry: list[datetime] = []
        for permission in role["permissions"]:
            expiries = [
                binding.expires_at
                for binding in bindings
                if binding.permission == permission
                and binding.effect == "allow"
                and binding.expires_at is not None
                and evaluate(permission, [binding], storage_space_id=None, object_key="").decision
                == Decision.ALLOW
            ]
            if not expiries:
                await self._audit_delegation_denial(context, "expiry_exceeds_authority")
                raise ApiError(
                    "delegation_exceeds_authority",
                    "Delegation expiry exceeds authority",
                    status_code=403,
                )
            per_permission_expiry.append(max(expiries))
        # Roles with no permissions still receive a valid finite binding; this
        # avoids creating an effectively permanent artifact without authority.
        if not per_permission_expiry:
            raise ApiError("validation_failed", "Role must contain permissions", status_code=422)
        return min(per_permission_expiry)

    async def get_role_binding(self, context: PrincipalContext, binding_id: UUID) -> dict[str, Any]:
        return _found(
            await self.store.get_role_binding(context.tenant_id, binding_id), "Role binding"
        )

    async def revoke_role_binding(self, context: PrincipalContext, binding_id: UUID) -> None:
        if not await self.store.revoke_role_binding(context.tenant_id, binding_id):
            raise ApiError("resource_not_found", "Role binding not found", status_code=404)

    async def get_effective_permissions(
        self,
        context: PrincipalContext,
        principal_id: UUID,
    ) -> dict[str, Any]:
        await self._require_same_tenant(context.tenant_id, principal_id)
        bindings = await self._bindings(
            context.tenant_id,
            principal_id,
            include_tenant_member_baseline=(
                principal_id == context.principal_id and context.subject_kind == "human"
            ),
        )
        result = explain_permissions(
            principal_id,
            sorted(self.known_permissions),
            bindings,
            authorization_version=context.authorization_version,
        )
        return {
            "principal_id": str(result.principal_id),
            "authorization_version": result.authorization_version,
            "evaluated_at": result.evaluated_at,
            "permissions": [
                {
                    "permission": item.permission,
                    "decision": item.decision,
                    "reason_code": item.reason_code,
                    "sources": [_source(source) for source in item.sources],
                }
                for item in result.permissions
            ],
        }

    async def simulate_authorization(self, context: PrincipalContext, body: Any) -> dict[str, Any]:
        principal_id = body.principal_id
        await self._require_same_tenant(context.tenant_id, principal_id)
        self._validate_permissions([body.permission])
        result = simulate(
            body.permission,
            await self._bindings(
                context.tenant_id,
                principal_id,
                include_tenant_member_baseline=(
                    principal_id == context.principal_id and context.subject_kind == "human"
                ),
            ),
            authorization_version=context.authorization_version,
        )
        sources = cast(list[Any], result["sources"])
        return {**result, "sources": [_source(source) for source in sources]}

    async def _bindings(
        self,
        tenant_id: UUID,
        principal_id: UUID,
        *,
        include_platform_tenant_admin: bool = True,
        include_tenant_member_baseline: bool = False,
    ) -> list[Binding]:
        bindings = [
            Binding(**row)
            for row in await self.store.bindings_for_principal(tenant_id, principal_id)
        ]
        # Tenant sessions are issued only for active tenant memberships.  Give
        # the current human member a small virtual baseline so invitation
        # acceptance always leads to a usable (read-only) tenant landing page.
        # Explicit deny bindings still win in the evaluator.
        if include_tenant_member_baseline:
            bindings.extend(
                Binding(
                    id=uuid5(NAMESPACE_URL, f"s3mp:tenant-member:{tenant_id}:{permission}"),
                    permission=permission,
                    effect=Decision.ALLOW,
                    storage_space_id=None,
                    canonical_prefix=None,
                    starts_at=datetime.min.replace(tzinfo=UTC),
                    expires_at=datetime.max.replace(tzinfo=UTC),
                    reason="tenant member baseline",
                )
                for permission in TENANT_MEMBER_PERMISSIONS
            )
        resolver = getattr(self.store, "platform_tenant_admin_binding", None)
        if (
            not include_platform_tenant_admin
            or resolver is None
            or self.tenant_admin_permissions is None
        ):
            return bindings
        platform_binding = await resolver(tenant_id, principal_id)
        if platform_binding is None:
            return bindings
        bindings.extend(
            Binding(
                id=platform_binding["id"],
                permission=permission,
                effect=Decision.ALLOW,
                storage_space_id=None,
                canonical_prefix=None,
                starts_at=platform_binding["starts_at"],
                expires_at=platform_binding["expires_at"],
                reason=platform_binding["reason"],
            )
            for permission in self.tenant_admin_permissions
        )
        return bindings

    async def _require_delegable_subset(
        self,
        context: PrincipalContext,
        permissions: list[str],
        storage_space_id: UUID | None,
        prefix: str | None,
        *,
        bypass: bool = False,
    ) -> None:
        if bypass:
            return
        bindings = await self._bindings(
            context.tenant_id,
            context.principal_id,
            include_tenant_member_baseline=context.subject_kind == "human",
        )
        for permission in permissions:
            if (
                evaluate(
                    permission, bindings, storage_space_id=storage_space_id, object_key=prefix or ""
                ).decision
                != Decision.ALLOW
            ):
                await self._audit_delegation_denial(
                    context, "permission_or_scope_exceeds_authority"
                )
                raise ApiError(
                    "delegation_exceeds_authority", "Delegation exceeds authority", status_code=403
                )

    async def _require_delegation_expiry_bound(
        self,
        context: PrincipalContext,
        permissions: list[str],
        storage_space_id: UUID | None,
        prefix: str | None,
        expires_at: datetime,
    ) -> None:
        bindings = await self._bindings(
            context.tenant_id,
            context.principal_id,
            include_tenant_member_baseline=context.subject_kind == "human",
        )
        for permission in permissions:
            matching = [
                binding
                for binding in bindings
                if binding.permission == permission
                and binding.effect == "allow"
                and binding.expires_at is not None
                and binding.expires_at >= expires_at
                and evaluate(
                    permission,
                    [binding],
                    storage_space_id=storage_space_id,
                    object_key=prefix or "",
                ).decision
                == Decision.ALLOW
            ]
            if not matching:
                await self._audit_delegation_denial(context, "expiry_exceeds_authority")
                raise ApiError(
                    "delegation_exceeds_authority",
                    "Delegation expiry exceeds authority",
                    status_code=403,
                )

    async def _audit_delegation_denial(self, context: PrincipalContext, reason_code: str) -> None:
        writer = getattr(self.store, "record_security_audit", None)
        if writer is None:
            return
        await writer(
            context.tenant_id,
            context.principal_id,
            "authorization.delegation_denied",
            "role_binding",
            None,
            {"reason_code": reason_code},
        )

    async def _require_same_tenant(self, tenant_id: UUID, principal_id: UUID) -> None:
        if await self.store.get_principal(tenant_id, principal_id) is None:
            raise ApiError("resource_not_found", "Principal not found", status_code=404)

    def _validate_permissions(self, permissions: list[str]) -> None:
        unknown = set(permissions) - self.known_permissions
        if unknown:
            raise ApiError(
                "validation_failed",
                "Unknown permission",
                status_code=422,
                details={"permissions": sorted(unknown)},
            )

    async def _is_platform_tenant_admin(self, context: PrincipalContext) -> bool:
        if context.subject_kind != "human" or self.tenant_admin_permissions is None:
            return False
        resolver = getattr(self.store, "platform_tenant_admin_binding", None)
        if resolver is None:
            return False
        return await resolver(context.tenant_id, context.principal_id) is not None

    def _validate_delegable_permissions(
        self, permissions: list[str], *, allow_non_delegable: bool = False
    ) -> None:
        if self.delegable_permissions is None:
            return
        if allow_non_delegable:
            return
        forbidden = set(permissions) - self.delegable_permissions
        if forbidden:
            raise ApiError(
                "delegation_exceeds_authority", "Permission is not delegable", status_code=403
            )


def _found(value: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if value is None:
        raise ApiError("resource_not_found", f"{label} not found", status_code=404)
    return value


def _source(value: Any) -> dict[str, Any]:
    return {
        "source_type": (
            "platform_role"
            if value.reason_code == "platform_tenant_admin"
            else ("role_binding" if value.binding_id else "default")
        ),
        "source_id": str(value.binding_id) if value.binding_id else None,
        "effect": value.effect,
        "reason_code": value.reason_code,
    }
