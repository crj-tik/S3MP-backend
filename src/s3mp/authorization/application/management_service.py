"""Application service for tenant-scoped authorization management."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from s3mp.authorization.application.explain import explain_permissions, simulate
from s3mp.authorization.domain.evaluator import (
    Binding,
    Decision,
    evaluate,
    validate_canonical_prefix,
)
from s3mp.common.errors import ApiError
from s3mp.identity.application.management_ports import AuthorizationManagementStore
from s3mp.identity.domain.context import PrincipalContext


@dataclass(slots=True)
class AuthorizationManagementService:
    store: AuthorizationManagementStore
    known_permissions: frozenset[str]

    async def require_permission(self, context: PrincipalContext, permission: str) -> None:
        bindings = await self._bindings(context.tenant_id, context.principal_id)
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
        self._validate_permissions(body.permissions)
        try:
            return await self.store.create_role(
                context.tenant_id, body.name, body.description, body.permissions
            )
        except ValueError as exc:
            raise ApiError("duplicate_resource", "Role already exists", status_code=409) from exc

    async def get_role(self, context: PrincipalContext, role_id: UUID) -> dict[str, Any]:
        return _found(await self.store.get_role(context.tenant_id, role_id), "Role")

    async def update_role(
        self, context: PrincipalContext, role_id: UUID, body: Any
    ) -> dict[str, Any]:
        self._validate_permissions(body.permissions)
        try:
            result = await self.store.update_role(
                context.tenant_id, role_id, body.name, body.description, body.permissions
            )
        except ValueError as exc:
            raise ApiError("validation_failed", str(exc), status_code=422) from exc
        return _found(result, "Role")

    async def list_role_bindings(
        self, context: PrincipalContext, principal_id: UUID | None = None, **page: Any
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        if (
            principal_id is not None
            and await self.store.get_principal(context.tenant_id, principal_id) is None
        ):
            raise ApiError("resource_not_found", "Principal not found", status_code=404)
        return await self.store.list_role_bindings(context.tenant_id, principal_id, **page)

    async def create_role_binding(self, context: PrincipalContext, body: Any) -> dict[str, Any]:
        role = await self.store.get_role(context.tenant_id, body.role_id)
        if (
            role is None
            or await self.store.get_principal(context.tenant_id, body.principal_id) is None
        ):
            raise ApiError("resource_not_found", "Role or principal not found", status_code=404)
        scope = body.scope
        if scope.type == "tenant" and (
            scope.storage_space_id is not None or scope.canonical_prefix is not None
        ):
            raise ApiError(
                "validation_failed",
                "Tenant scope cannot contain resource constraints",
                status_code=422,
            )
        if scope.type == "storage_space" and (
            scope.storage_space_id is None or scope.canonical_prefix is not None
        ):
            raise ApiError(
                "validation_failed",
                "Storage-space scope requires only storage_space_id",
                status_code=422,
            )
        if scope.type == "directory" and (
            scope.storage_space_id is None or scope.canonical_prefix is None
        ):
            raise ApiError(
                "validation_failed",
                "Directory scope requires storage_space_id and canonical_prefix",
                status_code=422,
            )
        if _requires_storage_scope(role["permissions"]) and scope.type == "tenant":
            raise ApiError(
                "validation_failed",
                "File permissions require a storage-space scope",
                status_code=422,
            )
        if scope.storage_space_id is not None and not await self.store.storage_space_exists(
            context.tenant_id, scope.storage_space_id
        ):
            raise ApiError("resource_not_found", "Storage space not found", status_code=404)
        if scope.canonical_prefix is not None:
            try:
                validate_canonical_prefix(scope.canonical_prefix)
            except ValueError as exc:
                raise ApiError(
                    "invalid_object_key", "Invalid canonical prefix", status_code=422
                ) from exc
        await self._require_delegable_subset(
            context, role["permissions"], scope.storage_space_id, scope.canonical_prefix
        )
        if body.expires_at <= datetime.now(UTC):
            raise ApiError("validation_failed", "expires_at must be in the future", status_code=422)
        result = await self.store.create_role_binding(
            context.tenant_id,
            body.principal_id,
            body.role_id,
            body.effect,
            scope.storage_space_id,
            scope.canonical_prefix,
            body.reason,
            body.starts_at,
            body.expires_at,
            context.principal_id,
        )
        return _found(result, "Role binding")

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
        _storage_space_id: UUID | None = None,
        object_key: str | None = None,
    ) -> dict[str, Any]:
        await self._require_same_tenant(context.tenant_id, principal_id)
        bindings = await self._bindings(context.tenant_id, principal_id)
        result = explain_permissions(
            principal_id,
            sorted(self.known_permissions),
            bindings,
            authorization_version=context.authorization_version,
            storage_space_id=_storage_space_id,
            object_key=object_key or "",
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
            await self._bindings(context.tenant_id, principal_id),
            authorization_version=context.authorization_version,
            storage_space_id=body.storage_space_id,
            object_key=body.object_key or "",
        )
        return {**result, "sources": [_source(source) for source in result["sources"]]}

    async def _bindings(self, tenant_id: UUID, principal_id: UUID) -> list[Binding]:
        return [
            Binding(**row)
            for row in await self.store.bindings_for_principal(tenant_id, principal_id)
        ]

    async def _require_delegable_subset(
        self,
        context: PrincipalContext,
        permissions: list[str],
        storage_space_id: UUID | None,
        prefix: str | None,
    ) -> None:
        bindings = await self._bindings(context.tenant_id, context.principal_id)
        for permission in permissions:
            if (
                evaluate(
                    permission, bindings, storage_space_id=storage_space_id, object_key=prefix or ""
                ).decision
                != Decision.ALLOW
            ):
                raise ApiError(
                    "delegation_exceeds_authority", "Delegation exceeds authority", status_code=403
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


def _found(value: dict[str, Any] | None, label: str) -> dict[str, Any]:
    if value is None:
        raise ApiError("resource_not_found", f"{label} not found", status_code=404)
    return value


def _source(value: Any) -> dict[str, Any]:
    return {
        "source_type": "role_binding" if value.binding_id else "default",
        "source_id": str(value.binding_id) if value.binding_id else None,
        "effect": value.effect,
        "reason_code": value.reason_code,
    }


def _requires_storage_scope(permissions: list[str]) -> bool:
    return any(
        permission.startswith(("files.", "multipart.", "presigned_urls."))
        for permission in permissions
    )
