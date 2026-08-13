"""Tenant-scoped persistence used by identity and authorization management."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.applications.infrastructure.models import ApplicationModel, ApplicationOwnerModel
from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.authorization.infrastructure.models import (
    GroupMemberModel,
    GroupModel,
    PermissionModel,
    RoleBindingModel,
    RoleModel,
    RolePermissionModel,
)
from s3mp.common.api.etag import etag_value
from s3mp.identity.infrastructure.models import (
    MembershipModel,
    MembershipStatus,
    MembershipStatusHistoryModel,
    PrincipalModel,
    PrincipalType,
    SessionModel,
    UserModel,
)
from s3mp.tenant.infrastructure.models import TenantModel


class SqlAlchemyIdentityAdminStore:
    """Explicit persistence boundary for identity and authorization services."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get_member(self, tenant_id: UUID, membership_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(MembershipModel)
                .join(TenantModel, TenantModel.id == MembershipModel.tenant_id)
                .where(MembershipModel.tenant_id == tenant_id, MembershipModel.id == membership_id)
            )
            if row is None:
                return None
            user = await session.get(UserModel, row.user_id)
            result = _membership_dict(row, user)
            tenant_status = await session.scalar(
                select(TenantModel.status).where(TenantModel.id == tenant_id)
            )
            result["tenant_status"] = _enum_value(tenant_status)
            return result

    get_membership = get_member

    async def get_membership_state(
        self, tenant_id: UUID, membership_id: UUID
    ) -> dict[str, Any] | None:
        """Internal, time-typed membership state for delayed-work validation."""
        async with self._sf() as session:
            row = await session.scalar(
                select(MembershipModel).where(
                    MembershipModel.tenant_id == tenant_id,
                    MembershipModel.id == membership_id,
                )
            )
            if row is None:
                return None
            return {
                "id": str(row.id),
                "principal_id": str(row.principal_id),
                "status": _enum_value(row.status),
                "authorization_version": row.authorization_version,
                "expires_at": row.expires_at,
                "tenant_status": _enum_value(
                    await session.scalar(
                        select(TenantModel.status).where(TenantModel.id == tenant_id)
                    )
                ),
            }

    async def get_principal(self, tenant_id: UUID, principal_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(PrincipalModel).where(
                    PrincipalModel.tenant_id == tenant_id, PrincipalModel.id == principal_id
                )
            )
            return _principal_dict(row) if row else None

    async def list_users(
        self, tenant_id: UUID, limit: int = 50, cursor: UUID | None = None
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        async with self._sf() as session:
            statement = (
                select(UserModel)
                .join(MembershipModel)
                .where(MembershipModel.tenant_id == tenant_id)
                .order_by(UserModel.id)
                .limit(limit + 1)
            )
            if cursor is not None:
                statement = statement.where(UserModel.id > cursor)
            rows = (await session.scalars(statement)).all()
            return [_user_dict(row) for row in rows[:limit]], rows[limit - 1].id if len(
                rows
            ) > limit else None

    async def get_user(self, tenant_id: UUID, user_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(UserModel)
                .join(MembershipModel)
                .where(MembershipModel.tenant_id == tenant_id, UserModel.id == user_id)
            )
            return _user_dict(row) if row else None

    async def create_member(
        self, tenant_id: UUID, email: str, display_name: str | None
    ) -> dict[str, Any]:
        normalized_email = email.strip().lower()
        async with self._sf.begin() as session:
            user = await session.scalar(
                select(UserModel).where(UserModel.normalized_email == normalized_email)
            )
            if user is None:
                user = UserModel(
                    email=email.strip(),
                    normalized_email=normalized_email,
                    display_name=display_name or normalized_email,
                )
                session.add(user)
                await session.flush()
            existing = await session.scalar(
                select(MembershipModel).where(
                    MembershipModel.tenant_id == tenant_id, MembershipModel.user_id == user.id
                )
            )
            if existing is not None:
                raise ValueError("membership already exists")
            principal = PrincipalModel(
                tenant_id=tenant_id,
                type=PrincipalType.USER,
                display_name=display_name or user.display_name,
            )
            session.add(principal)
            await session.flush()
            membership = MembershipModel(
                tenant_id=tenant_id,
                user_id=user.id,
                principal_id=principal.id,
                status=MembershipStatus.INVITED,
            )
            session.add(membership)
            await session.flush()
            return _membership_dict(membership, user)

    async def list_members(
        self, tenant_id: UUID, limit: int = 50, cursor: UUID | None = None
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        async with self._sf() as session:
            statement = (
                select(MembershipModel)
                .where(MembershipModel.tenant_id == tenant_id)
                .order_by(MembershipModel.id)
                .limit(limit + 1)
            )
            if cursor is not None:
                statement = statement.where(MembershipModel.id > cursor)
            rows = (await session.scalars(statement)).all()
            user_ids = [row.user_id for row in rows[:limit]]
            users = (
                {
                    row.id: row
                    for row in (
                        await session.scalars(select(UserModel).where(UserModel.id.in_(user_ids)))
                    ).all()
                }
                if user_ids
                else {}
            )
            return (
                [_membership_dict(row, users.get(row.user_id)) for row in rows[:limit]],
                rows[limit - 1].id if len(rows) > limit else None,
            )

    async def update_member(
        self, tenant_id: UUID, membership_id: UUID, status: str, reason: str, changed_by: UUID
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MembershipModel)
                .where(MembershipModel.tenant_id == tenant_id, MembershipModel.id == membership_id)
                .with_for_update()
            )
            if row is None:
                return None
            old_status = row.status
            row.status = MembershipStatus(status)
            row.authorization_version += 1
            session.add(
                MembershipStatusHistoryModel(
                    tenant_id=tenant_id,
                    membership_id=membership_id,
                    from_status=old_status,
                    to_status=row.status,
                    reason=reason,
                    changed_by_principal_id=changed_by,
                )
            )
            await session.execute(
                update(SessionModel)
                .where(
                    SessionModel.tenant_id == tenant_id,
                    SessionModel.membership_id == membership_id,
                    SessionModel.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
            # Keep application containment in this membership mutation
            # transaction: a direct owner row is insufficient when suspended.
            app_ids = list(
                (
                    await session.scalars(
                        select(ApplicationOwnerModel.application_id).where(
                            ApplicationOwnerModel.tenant_id == tenant_id,
                            ApplicationOwnerModel.owner_principal_id == row.principal_id,
                        )
                    )
                ).all()
            )
            if status != "active":
                for app_id in app_ids:
                    active_owner = await session.scalar(
                        select(ApplicationOwnerModel.id)
                        .join(
                            MembershipModel,
                            (
                                (MembershipModel.tenant_id == ApplicationOwnerModel.tenant_id)
                                & (
                                    MembershipModel.principal_id
                                    == ApplicationOwnerModel.owner_principal_id
                                )
                            ),
                        )
                        .where(
                            ApplicationOwnerModel.tenant_id == tenant_id,
                            ApplicationOwnerModel.application_id == app_id,
                            MembershipModel.status == MembershipStatus.ACTIVE,
                            (
                                MembershipModel.expires_at.is_(None)
                                | (MembershipModel.expires_at > datetime.now(UTC))
                            ),
                        )
                    )
                    if active_owner is None:
                        result = await session.execute(
                            update(ApplicationModel)
                            .where(
                                ApplicationModel.tenant_id == tenant_id,
                                ApplicationModel.id == app_id,
                                ApplicationModel.status == "active",
                            )
                            .values(
                                status="pending_takeover",
                                authorization_version=ApplicationModel.authorization_version + 1,
                            )
                        )
                        if getattr(result, "rowcount", 0):
                            session.add(
                                AuditEventModel(
                                    tenant_id=tenant_id,
                                    actor_principal_id=changed_by,
                                    action="application.ownerless_contained",
                                    resource_type="application",
                                    resource_id=str(app_id),
                                    details={"reason_code": "no_active_owner"},
                                )
                            )
            await session.flush()
            user = await session.get(UserModel, row.user_id)
            return _membership_dict(row, user)

    async def list_groups(
        self, tenant_id: UUID, limit: int = 50, cursor: UUID | None = None
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        async with self._sf() as session:
            statement = (
                select(GroupModel)
                .where(GroupModel.tenant_id == tenant_id)
                .order_by(GroupModel.id)
                .limit(limit + 1)
            )
            if cursor is not None:
                statement = statement.where(GroupModel.id > cursor)
            rows = (await session.scalars(statement)).all()
            return (
                [await self._group_projection(session, row) for row in rows[:limit]],
                rows[limit - 1].id if len(rows) > limit else None,
            )

    async def get_group(self, tenant_id: UUID, group_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(GroupModel).where(
                    GroupModel.tenant_id == tenant_id, GroupModel.id == group_id
                )
            )
            return await self._group_projection(session, row) if row else None

    async def create_group(
        self, tenant_id: UUID, name: str, description: str | None, _created_by: UUID
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            principal = PrincipalModel(
                tenant_id=tenant_id, type=PrincipalType.GROUP, display_name=name
            )
            session.add(principal)
            await session.flush()
            group = GroupModel(
                tenant_id=tenant_id, principal_id=principal.id, name=name, description=description
            )
            session.add(group)
            await session.flush()
            return await self._group_projection(session, group)

    async def update_group(
        self, tenant_id: UUID, group_id: UUID, name: str | None, description: str | None
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(GroupModel)
                .where(GroupModel.tenant_id == tenant_id, GroupModel.id == group_id)
                .with_for_update()
            )
            if row is None:
                return None
            if name is not None:
                row.name = name
                principal = await session.get(PrincipalModel, row.principal_id)
                if principal is not None:
                    principal.display_name = name
            if description is not None:
                row.description = description
            await session.flush()
            return await self._group_projection(session, row)

    async def delete_group(self, tenant_id: UUID, group_id: UUID) -> bool:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(GroupModel)
                .where(GroupModel.tenant_id == tenant_id, GroupModel.id == group_id)
                .with_for_update()
            )
            if row is None:
                return False
            principal_id = row.principal_id
            await self._bump_affected_principals(session, tenant_id, principal_id)
            await session.delete(row)
            principal = await session.get(PrincipalModel, principal_id)
            if principal is not None:
                await session.delete(principal)
            return True

    async def list_group_members(
        self, tenant_id: UUID, group_id: UUID, limit: int = 50, cursor: UUID | None = None
    ) -> tuple[list[dict[str, Any]], UUID | None] | None:
        async with self._sf() as session:
            group = await session.scalar(
                select(GroupModel).where(
                    GroupModel.tenant_id == tenant_id, GroupModel.id == group_id
                )
            )
            if group is None:
                return None
            statement = (
                select(MembershipModel)
                .join(
                    GroupMemberModel, GroupMemberModel.principal_id == MembershipModel.principal_id
                )
                .where(
                    GroupMemberModel.tenant_id == tenant_id,
                    GroupMemberModel.group_id == group_id,
                    MembershipModel.tenant_id == tenant_id,
                )
                .order_by(MembershipModel.id)
                .limit(limit + 1)
            )
            if cursor is not None:
                statement = statement.where(MembershipModel.id > cursor)
            rows = (await session.scalars(statement)).all()
            users = (
                {
                    row.id: row
                    for row in (
                        await session.scalars(
                            select(UserModel).where(
                                UserModel.id.in_([member.user_id for member in rows[:limit]])
                            )
                        )
                    ).all()
                }
                if rows
                else {}
            )
            return (
                [_membership_dict(member, users.get(member.user_id)) for member in rows[:limit]],
                rows[limit - 1].id if len(rows) > limit else None,
            )

    async def add_group_member(self, tenant_id: UUID, group_id: UUID, membership_id: UUID) -> bool:
        async with self._sf.begin() as session:
            group = await session.scalar(
                select(GroupModel)
                .where(GroupModel.tenant_id == tenant_id, GroupModel.id == group_id)
                .with_for_update()
            )
            member = await session.scalar(
                select(MembershipModel).where(
                    MembershipModel.tenant_id == tenant_id, MembershipModel.id == membership_id
                )
            )
            if group is None or member is None:
                return False
            existing = await session.scalar(
                select(GroupMemberModel).where(
                    GroupMemberModel.tenant_id == tenant_id,
                    GroupMemberModel.group_id == group_id,
                    GroupMemberModel.principal_id == member.principal_id,
                )
            )
            if existing is not None:
                raise ValueError("group membership already exists")
            session.add(
                GroupMemberModel(
                    tenant_id=tenant_id, group_id=group_id, principal_id=member.principal_id
                )
            )
            await self._bump_membership_version(session, tenant_id, member.principal_id)
            return True

    async def remove_group_member(
        self, tenant_id: UUID, group_id: UUID, membership_id: UUID
    ) -> bool:
        async with self._sf.begin() as session:
            member = await session.scalar(
                select(MembershipModel).where(
                    MembershipModel.tenant_id == tenant_id, MembershipModel.id == membership_id
                )
            )
            if member is None:
                return False
            row = await session.scalar(
                select(GroupMemberModel)
                .where(
                    GroupMemberModel.tenant_id == tenant_id,
                    GroupMemberModel.group_id == group_id,
                    GroupMemberModel.principal_id == member.principal_id,
                )
                .with_for_update()
            )
            if row is None:
                return False
            await session.delete(row)
            await self._bump_membership_version(session, tenant_id, member.principal_id)
            return True

    async def list_roles(
        self, tenant_id: UUID, limit: int = 50, cursor: UUID | None = None
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        async with self._sf() as session:
            statement = (
                select(RoleModel)
                .where(RoleModel.tenant_id == tenant_id)
                .order_by(RoleModel.id)
                .limit(limit + 1)
            )
            if cursor is not None:
                statement = statement.where(RoleModel.id > cursor)
            rows = (await session.scalars(statement)).all()
            return (
                [await self._role_projection(session, row) for row in rows[:limit]],
                rows[limit - 1].id if len(rows) > limit else None,
            )

    async def get_role(self, tenant_id: UUID, role_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(RoleModel).where(RoleModel.tenant_id == tenant_id, RoleModel.id == role_id)
            )
            return await self._role_projection(session, row) if row else None

    async def create_role(
        self, tenant_id: UUID, name: str, description: str | None, permissions: list[str]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = RoleModel(tenant_id=tenant_id, name=name, description=description)
            session.add(row)
            await session.flush()
            await self._replace_role_permissions(session, row.id, permissions)
            return await self._role_projection(session, row)

    async def update_role(
        self,
        tenant_id: UUID,
        role_id: UUID,
        name: str | None,
        description: str | None,
        permissions: list[str] | None,
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(RoleModel)
                .where(RoleModel.tenant_id == tenant_id, RoleModel.id == role_id)
                .with_for_update()
            )
            if row is None:
                return None
            if name is not None:
                row.name = name
            if description is not None:
                row.description = description
            if permissions is not None:
                await self._replace_role_permissions(session, row.id, permissions)
            await self._bump_bound_principals(session, tenant_id, row.id)
            await session.flush()
            return await self._role_projection(session, row)

    async def list_role_bindings(
        self,
        tenant_id: UUID,
        principal_id: UUID | None = None,
        limit: int = 50,
        cursor: UUID | None = None,
    ) -> tuple[list[dict[str, Any]], UUID | None]:
        async with self._sf() as session:
            statement = (
                select(RoleBindingModel)
                .where(
                    RoleBindingModel.tenant_id == tenant_id, RoleBindingModel.revoked_at.is_(None)
                )
                .order_by(RoleBindingModel.id)
                .limit(limit + 1)
            )
            if principal_id is not None:
                statement = statement.where(RoleBindingModel.principal_id == principal_id)
            if cursor is not None:
                statement = statement.where(RoleBindingModel.id > cursor)
            rows = (await session.scalars(statement)).all()
            return (
                [await self._binding_projection(session, row) for row in rows[:limit]],
                rows[limit - 1].id if len(rows) > limit else None,
            )

    async def get_role_binding(self, tenant_id: UUID, binding_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(RoleBindingModel).where(
                    RoleBindingModel.tenant_id == tenant_id,
                    RoleBindingModel.id == binding_id,
                    RoleBindingModel.revoked_at.is_(None),
                )
            )
            return await self._binding_projection(session, row) if row else None

    async def create_role_binding(
        self,
        tenant_id: UUID,
        principal_id: UUID,
        role_id: UUID,
        effect: str,
        storage_space_id: UUID | None,
        canonical_prefix: str | None,
        reason: str,
        starts_at: datetime | None,
        expires_at: datetime,
        created_by: UUID,
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            principal = await session.scalar(
                select(PrincipalModel).where(
                    PrincipalModel.tenant_id == tenant_id, PrincipalModel.id == principal_id
                )
            )
            role = await session.scalar(
                select(RoleModel).where(RoleModel.tenant_id == tenant_id, RoleModel.id == role_id)
            )
            if principal is None or role is None:
                return None
            row = RoleBindingModel(
                tenant_id=tenant_id,
                principal_id=principal_id,
                role_id=role_id,
                effect=effect,
                storage_space_id=storage_space_id,
                canonical_prefix=canonical_prefix,
                reason=reason,
                starts_at=starts_at or datetime.now(UTC),
                expires_at=expires_at,
                created_by_principal_id=created_by,
            )
            session.add(row)
            await session.flush()
            await self._bump_affected_principals(session, tenant_id, principal_id)
            return await self._binding_projection(session, row)

    async def revoke_role_binding(self, tenant_id: UUID, binding_id: UUID) -> bool:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(RoleBindingModel)
                .where(
                    RoleBindingModel.tenant_id == tenant_id,
                    RoleBindingModel.id == binding_id,
                    RoleBindingModel.revoked_at.is_(None),
                )
                .with_for_update()
            )
            if row is None:
                return False
            row.revoked_at = datetime.now(UTC)
            await self._bump_affected_principals(session, tenant_id, row.principal_id)
            return True

    async def bindings_for_principal(
        self, tenant_id: UUID, principal_id: UUID
    ) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        async with self._sf() as session:
            group_principals = (
                await session.scalars(
                    select(GroupModel.principal_id)
                    .join(GroupMemberModel, GroupMemberModel.group_id == GroupModel.id)
                    .where(
                        GroupModel.tenant_id == tenant_id,
                        GroupModel.enabled.is_(True),
                        GroupMemberModel.tenant_id == tenant_id,
                        GroupMemberModel.principal_id == principal_id,
                    )
                )
            ).all()
            rows = await session.execute(
                select(RoleBindingModel, PermissionModel.name)
                .join(RolePermissionModel, RolePermissionModel.role_id == RoleBindingModel.role_id)
                .join(PermissionModel, PermissionModel.id == RolePermissionModel.permission_id)
                .where(
                    RoleBindingModel.tenant_id == tenant_id,
                    RoleBindingModel.principal_id.in_([principal_id, *group_principals]),
                    RoleBindingModel.revoked_at.is_(None),
                    RoleBindingModel.starts_at <= now,
                    RoleBindingModel.expires_at > now,
                )
            )
            return [
                {
                    "id": binding.id,
                    "permission": permission,
                    "effect": _enum_value(binding.effect),
                    "storage_space_id": binding.storage_space_id,
                    "canonical_prefix": binding.canonical_prefix,
                    "starts_at": binding.starts_at,
                    "expires_at": binding.expires_at,
                    "reason": binding.reason,
                }
                for binding, permission in rows
            ]

    async def bindings_for_role(self, tenant_id: UUID, role_id: UUID) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        async with self._sf() as session:
            rows = (
                await session.scalars(
                    select(RoleBindingModel).where(
                        RoleBindingModel.tenant_id == tenant_id,
                        RoleBindingModel.role_id == role_id,
                        RoleBindingModel.revoked_at.is_(None),
                        RoleBindingModel.starts_at <= now,
                        RoleBindingModel.expires_at > now,
                    )
                )
            ).all()
            return [
                {"storage_space_id": row.storage_space_id, "canonical_prefix": row.canonical_prefix}
                for row in rows
            ]

    async def record_security_audit(
        self,
        tenant_id: UUID,
        actor_principal_id: UUID,
        action: str,
        resource_type: str,
        resource_id: str | None,
        details: dict[str, object],
    ) -> None:
        async with self._sf.begin() as session:
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=actor_principal_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details,
                )
            )

    async def tenant_context(self, tenant_id: UUID, principal_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.execute(
                select(PrincipalModel, MembershipModel, TenantModel)
                .join(MembershipModel, MembershipModel.principal_id == PrincipalModel.id)
                .join(TenantModel, TenantModel.id == MembershipModel.tenant_id)
                .where(MembershipModel.tenant_id == tenant_id, PrincipalModel.id == principal_id)
            )
            result = row.first()
            if result is None:
                return None
            principal, membership, tenant = result
            return {
                "principal": _principal_dict(principal),
                "current_tenant": {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "membership_status": _enum_value(membership.status),
                },
                "authorization_version": membership.authorization_version,
            }

    async def storage_space_exists(self, tenant_id: UUID, storage_space_id: UUID) -> bool:
        from s3mp.storage.infrastructure.models import StorageSpaceModel

        async with self._sf() as session:
            return (
                await session.scalar(
                    select(StorageSpaceModel.id).where(
                        StorageSpaceModel.tenant_id == tenant_id,
                        StorageSpaceModel.id == storage_space_id,
                    )
                )
                is not None
            )

    async def tenant_memberships_for_principal(self, principal_id: UUID) -> list[dict[str, Any]]:
        async with self._sf() as session:
            rows = await session.execute(
                select(MembershipModel, TenantModel)
                .join(TenantModel, TenantModel.id == MembershipModel.tenant_id)
                .where(MembershipModel.principal_id == principal_id)
            )
            return [
                {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "membership_status": _enum_value(member.status),
                }
                for member, tenant in rows
            ]

    async def _replace_role_permissions(
        self, session: AsyncSession, role_id: UUID, names: list[str]
    ) -> None:
        expected = sorted(set(names))
        permissions = (
            (
                await session.scalars(
                    select(PermissionModel).where(PermissionModel.name.in_(expected))
                )
            ).all()
            if expected
            else []
        )
        found = {permission.name for permission in permissions}
        if found != set(expected):
            raise ValueError("unknown permissions: " + ", ".join(sorted(set(expected) - found)))
        await session.execute(
            delete(RolePermissionModel).where(RolePermissionModel.role_id == role_id)
        )
        session.add_all(
            [
                RolePermissionModel(role_id=role_id, permission_id=permission.id)
                for permission in permissions
            ]
        )

    async def _bump_membership_version(
        self, session: AsyncSession, tenant_id: UUID, principal_id: UUID
    ) -> None:
        await session.execute(
            update(MembershipModel)
            .where(
                MembershipModel.tenant_id == tenant_id, MembershipModel.principal_id == principal_id
            )
            .values(authorization_version=MembershipModel.authorization_version + 1)
        )
        await session.execute(
            update(SessionModel)
            .where(
                SessionModel.tenant_id == tenant_id,
                SessionModel.principal_id == principal_id,
                SessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )

    async def _bump_bound_principals(
        self, session: AsyncSession, tenant_id: UUID, role_id: UUID
    ) -> None:
        principals = (
            await session.scalars(
                select(RoleBindingModel.principal_id).where(
                    RoleBindingModel.tenant_id == tenant_id,
                    RoleBindingModel.role_id == role_id,
                    RoleBindingModel.revoked_at.is_(None),
                )
            )
        ).all()
        for principal_id in principals:
            await self._bump_affected_principals(session, tenant_id, principal_id)

    async def _bump_affected_principals(
        self, session: AsyncSession, tenant_id: UUID, principal_id: UUID
    ) -> None:
        """Invalidate a direct subject or every member of a group subject atomically."""
        principal = await session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.tenant_id == tenant_id, PrincipalModel.id == principal_id
            )
        )
        if principal is None:
            return
        if principal.type != PrincipalType.GROUP:
            await self._bump_membership_version(session, tenant_id, principal_id)
            await session.execute(
                update(ApplicationModel)
                .where(
                    ApplicationModel.tenant_id == tenant_id,
                    ApplicationModel.principal_id == principal_id,
                )
                .values(authorization_version=ApplicationModel.authorization_version + 1)
            )
            return
        group_id = await session.scalar(
            select(GroupModel.id).where(
                GroupModel.tenant_id == tenant_id, GroupModel.principal_id == principal_id
            )
        )
        if group_id is None:
            return
        members = (
            await session.scalars(
                select(GroupMemberModel.principal_id).where(
                    GroupMemberModel.tenant_id == tenant_id, GroupMemberModel.group_id == group_id
                )
            )
        ).all()
        for member_principal_id in members:
            await self._bump_membership_version(session, tenant_id, member_principal_id)
            await session.execute(
                update(ApplicationModel)
                .where(
                    ApplicationModel.tenant_id == tenant_id,
                    ApplicationModel.principal_id == member_principal_id,
                )
                .values(authorization_version=ApplicationModel.authorization_version + 1)
            )

    async def _group_projection(self, session: AsyncSession, row: GroupModel) -> dict[str, Any]:
        count = await session.scalar(
            select(func.count())
            .select_from(GroupMemberModel)
            .where(GroupMemberModel.tenant_id == row.tenant_id, GroupMemberModel.group_id == row.id)
        )
        return _group_dict(row, int(count or 0))

    async def _role_projection(self, session: AsyncSession, row: RoleModel) -> dict[str, Any]:
        names = (
            await session.scalars(
                select(PermissionModel.name)
                .join(RolePermissionModel)
                .where(RolePermissionModel.role_id == row.id)
            )
        ).all()
        return _role_dict(row, list(names))

    async def _binding_projection(
        self, session: AsyncSession, row: RoleBindingModel
    ) -> dict[str, Any]:
        principal = await session.scalar(
            select(PrincipalModel).where(
                PrincipalModel.tenant_id == row.tenant_id, PrincipalModel.id == row.principal_id
            )
        )
        summary = (
            {
                "id": str(principal.id),
                "type": _enum_value(principal.type),
                "display_name": principal.display_name,
            }
            if principal
            else None
        )
        return _binding_dict(row, summary)


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _time(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _user_dict(row: UserModel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "email": row.email,
        "display_name": row.display_name,
        "status": _enum_value(row.status),
        "created_at": _time(row.created_at),
    }


def _membership_dict(row: MembershipModel, user: UserModel | None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "user": _user_dict(user) if user else None,
        "principal": {
            "id": str(row.principal_id),
            "type": "user",
            "display_name": user.display_name if user else "",
        },
        "status": _enum_value(row.status),
        "authorization_version": row.authorization_version,
        "created_at": _time(row.created_at),
        "updated_at": _time(row.updated_at),
        "etag": etag_value(str(row.id), _time(row.updated_at) or ""),
    }


def _group_dict(row: GroupModel, member_count: int) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "principal": {"id": str(row.principal_id), "type": "group", "display_name": row.name},
        "name": row.name,
        "description": row.description or "",
        "member_count": member_count,
        "created_at": _time(row.created_at),
        "updated_at": _time(row.updated_at),
        "etag": etag_value(str(row.id), _time(row.updated_at) or ""),
    }


def _role_dict(row: RoleModel, permissions: list[str]) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description or "",
        "permissions": sorted(permissions),
        "system": row.built_in,
        "created_at": _time(row.created_at),
        "updated_at": _time(row.updated_at),
        "etag": etag_value(str(row.id), _time(row.updated_at) or ""),
    }


def _binding_dict(row: RoleBindingModel, principal: dict[str, Any] | None) -> dict[str, Any]:
    scope_type = (
        "directory"
        if row.canonical_prefix is not None
        else "storage_space"
        if row.storage_space_id is not None
        else "tenant"
    )
    return {
        "id": str(row.id),
        "principal": principal,
        "role_id": str(row.role_id),
        "effect": _enum_value(row.effect),
        "scope": {
            "type": scope_type,
            "storage_space_id": str(row.storage_space_id) if row.storage_space_id else None,
            "canonical_prefix": row.canonical_prefix,
        },
        "reason": row.reason,
        "starts_at": _time(row.starts_at),
        "expires_at": _time(row.expires_at),
        "created_by": str(row.created_by_principal_id),
        "created_at": _time(row.created_at),
        "etag": etag_value(str(row.id), _time(row.created_at) or ""),
    }


def _principal_dict(row: PrincipalModel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "type": _enum_value(row.type),
        "display_name": row.display_name,
        "enabled": row.enabled,
        "created_at": _time(row.created_at),
        "updated_at": _time(row.updated_at),
    }
