"""Idempotent, immutable authorization baselines for platform and tenants."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from s3mp.authorization.infrastructure.models import PermissionModel, RoleModel, RolePermissionModel
from s3mp.platform.infrastructure.models import PlatformAuditEventModel, PlatformRoleModel

PLATFORM_ROLES: dict[str, tuple[str, ...]] = {
    "platform_admin": (
        "platform.accounts.read",
        "platform.accounts.manage",
        "platform.tenants.read",
        "platform.tenants.manage",
        "platform.roles.read",
        "platform.roles.manage",
        "platform.support.read",
        "platform.support.manage",
        "platform.quotas.read",
        "platform.audit.read",
        "platform.quotas.manage",
    ),
    "platform_operator": (
        "platform.accounts.read",
        "platform.tenants.read",
        "platform.support.read",
        "platform.support.manage",
        "platform.quotas.read",
    ),
    "platform_auditor": (
        "platform.tenants.read",
        "platform.roles.read",
        "platform.support.read",
        "platform.audit.read",
        "platform.quotas.read",
    ),
}

TENANT_ADMIN_PERMISSIONS: tuple[str, ...] = (
    "members.read",
    "members.manage",
    "groups.read",
    "groups.manage",
    "roles.read",
    "roles.manage",
    "role_bindings.read",
    "role_bindings.manage",
    "applications.read",
    "applications.manage",
    "api_keys.read",
    "api_keys.manage",
    "storage_connections.read",
    "storage_connections.manage",
    "storage_spaces.read",
    "storage_spaces.manage",
    "quotas.read",
    "quotas.manage",
    "audit.read",
)

SUPPORT_ROLE_PERMISSIONS: tuple[str, ...] = (
    "members.read",
    "groups.read",
    "roles.read",
    "role_bindings.read",
    "applications.read",
    "api_keys.read",
    "storage_connections.read",
    "storage_spaces.read",
    "quotas.read",
    "audit.read",
)

TENANT_PERMISSION_METADATA: dict[str, tuple[str, bool, str]] = {
    "members.read": ("membership", True, "List and view tenant members."),
    "members.manage": ("membership", True, "Manage tenant members."),
    "groups.read": ("group", True, "View groups and group membership."),
    "groups.manage": ("group", True, "Manage groups and group membership."),
    "roles.read": ("role", True, "View tenant roles."),
    "roles.manage": ("role", True, "Manage tenant roles."),
    "role_bindings.read": ("role_binding", True, "View scoped role bindings."),
    "role_bindings.manage": ("role_binding", True, "Manage scoped role bindings."),
    "applications.read": ("application", True, "View tenant applications."),
    "applications.manage": ("application", True, "Manage tenant applications."),
    "api_keys.read": ("api_key", True, "View API key metadata."),
    "api_keys.manage": ("api_key", True, "Manage application API keys."),
    "storage_connections.read": ("storage_connection", False, "View storage connections."),
    "storage_connections.manage": ("storage_connection", False, "Manage storage connections."),
    "storage_spaces.read": ("storage_space", True, "View storage spaces."),
    "storage_spaces.manage": ("storage_space", True, "Manage storage spaces."),
    "quotas.read": ("quota", True, "View quota configuration and usage."),
    "quotas.manage": ("quota", False, "Manage quota configuration."),
    "audit.read": ("audit_event", False, "Search tenant audit events."),
}


async def reconcile_platform_roles(session: AsyncSession) -> set[str]:
    """Add missing baseline permissions without modifying custom roles or removing grants."""
    existing = {
        role.name: role for role in (await session.scalars(select(PlatformRoleModel))).all()
    }
    changed: set[str] = set()
    for name, permissions in PLATFORM_ROLES.items():
        role = existing.get(name)
        if role is None:
            session.add(PlatformRoleModel(name=name, permissions=list(permissions), built_in=True))
            changed.add(name)
            continue
        if not role.built_in:
            continue
        merged = list(dict.fromkeys([*role.permissions, *permissions]))
        if merged != role.permissions:
            role.permissions = merged
            changed.add(name)
    if changed:
        session.add(
            PlatformAuditEventModel(
                actor_user_id=None,
                action="platform.role_baseline_reconciled",
                resource_type="platform_role",
                resource_id=None,
                details={"roles": sorted(changed)},
            )
        )
    return changed


async def seed_platform_roles(session: AsyncSession) -> None:
    """Backward-compatible bootstrap entry point for built-in platform roles."""
    await reconcile_platform_roles(session)


async def ensure_tenant_admin_role(session: AsyncSession, tenant_id: UUID) -> RoleModel:
    """Ensure the tenant-local built-in admin role has its baseline permissions."""
    role = await session.scalar(
        select(RoleModel).where(RoleModel.tenant_id == tenant_id, RoleModel.name == "tenant-admin")
    )
    if role is None:
        role = RoleModel(
            tenant_id=tenant_id,
            name="tenant-admin",
            description="Built-in tenant administrator baseline",
            built_in=True,
        )
        session.add(role)
        await session.flush()
    await _ensure_permissions(session, role, TENANT_ADMIN_PERMISSIONS)
    return role


async def ensure_support_role(session: AsyncSession, tenant_id: UUID) -> RoleModel:
    """Create the non-file-content role used only by expiring support access."""
    role = await session.scalar(
        select(RoleModel).where(
            RoleModel.tenant_id == tenant_id, RoleModel.name == "platform-support"
        )
    )
    if role is None:
        role = RoleModel(
            tenant_id=tenant_id,
            name="platform-support",
            description="Built-in time-bounded support baseline without file-content permissions",
            built_in=True,
        )
        session.add(role)
        await session.flush()
    await _ensure_permissions(session, role, SUPPORT_ROLE_PERMISSIONS)
    return role


async def _ensure_permissions(session: AsyncSession, role: RoleModel, names: Iterable[str]) -> None:
    expected_names = tuple(names)
    existing = {
        permission.name: permission
        for permission in (
            await session.scalars(
                select(PermissionModel).where(PermissionModel.name.in_(expected_names))
            )
        ).all()
    }
    for name in expected_names:
        if name not in existing:
            resource_type, delegable, description = TENANT_PERMISSION_METADATA[name]
            session.add(
                PermissionModel(
                    name=name,
                    resource_type=resource_type,
                    delegable=delegable,
                    description=description,
                )
            )
    if len(existing) != len(expected_names):
        await session.flush()
    permissions = list(
        (
            await session.scalars(
                select(PermissionModel).where(PermissionModel.name.in_(expected_names))
            )
        ).all()
    )
    existing_ids = set(
        (
            await session.scalars(
                select(RolePermissionModel.permission_id).where(
                    RolePermissionModel.role_id == role.id
                )
            )
        ).all()
    )
    for permission in permissions:
        if permission.id not in existing_ids:
            session.add(RolePermissionModel(role_id=role.id, permission_id=permission.id))
