"""SQLAlchemy repositories for identity management: memberships, groups, roles, bindings."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.authorization.infrastructure.models import (
    GroupMemberModel,
    GroupModel,
    RoleBindingModel,
    RoleModel,
)
from s3mp.identity.infrastructure.models import (
    MembershipModel,
    MembershipStatusHistoryModel,
    PrincipalModel,
    SessionModel,
    UserModel,
)


class SqlAlchemyIdentityAdminStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Members ───────────────────────────────────────────────────────────

    async def get_member(self, tenant_id: UUID, membership_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(MembershipModel).where(
                    MembershipModel.tenant_id == tenant_id,
                    MembershipModel.id == membership_id,
                )
            )
            return _membership_dict(row) if row else None

    get_membership = get_member  # Alias for IdentityContextProvider

    async def get_principal(self, tenant_id: UUID, principal_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(PrincipalModel).where(
                    PrincipalModel.tenant_id == tenant_id,
                    PrincipalModel.id == principal_id,
                )
            )
            return _principal_dict(row) if row else None

    async def list_members(
        self, tenant_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        async with self._sf() as session:
            stmt = select(MembershipModel).where(
                MembershipModel.tenant_id == tenant_id
            ).order_by(MembershipModel.created_at.desc()).limit(limit + 1)
            if cursor:
                stmt = stmt.where(MembershipModel.id > UUID(cursor))
            rows = (await session.scalars(stmt)).all()
            items = [_membership_dict(r) for r in rows[:limit]]
            next_cursor = str(rows[limit].id) if len(rows) > limit else None
            return items, next_cursor

    async def update_member(
        self, tenant_id: UUID, membership_id: UUID, status: str, reason: str, changed_by: UUID
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MembershipModel).where(
                    MembershipModel.tenant_id == tenant_id,
                    MembershipModel.id == membership_id,
                ).with_for_update()
            )
            if row is None:
                return None
            old_status = row.status
            row.status = status  # type: ignore[assignment]
            row.authorization_version = row.authorization_version + 1
            history = MembershipStatusHistoryModel(
                tenant_id=tenant_id, membership_id=membership_id,
                from_status=old_status, to_status=status,
                reason=reason, changed_by_principal_id=changed_by,
            )
            session.add(history)
            await session.flush()
            return _membership_dict(row)

    # ── Groups ────────────────────────────────────────────────────────────

    async def list_groups(
        self, tenant_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        async with self._sf() as session:
            stmt = select(GroupModel).where(
                GroupModel.tenant_id == tenant_id
            ).order_by(GroupModel.name).limit(limit + 1)
            if cursor:
                stmt = stmt.where(GroupModel.id > UUID(cursor))
            rows = (await session.scalars(stmt)).all()
            items = [_group_dict(r) for r in rows[:limit]]
            next_cursor = str(rows[limit].id) if len(rows) > limit else None
            return items, next_cursor

    async def get_group(self, tenant_id: UUID, group_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(GroupModel).where(
                    GroupModel.tenant_id == tenant_id, GroupModel.id == group_id
                )
            )
            return _group_dict(row) if row else None

    async def create_group(
        self, tenant_id: UUID, name: str, description: str | None, principal_id: UUID
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            model = GroupModel(
                tenant_id=tenant_id, name=name, description=description,
                principal_id=principal_id,
            )
            session.add(model)
            await session.flush()
            return _group_dict(model)

    async def update_group(
        self, tenant_id: UUID, group_id: UUID, name: str | None, description: str | None
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(GroupModel).where(
                    GroupModel.tenant_id == tenant_id, GroupModel.id == group_id
                ).with_for_update()
            )
            if row is None:
                return None
            if name: row.name = name
            if description: row.description = description
            await session.flush()
            return _group_dict(row)

    async def delete_group(self, tenant_id: UUID, group_id: UUID) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(GroupModel).where(
                    GroupModel.tenant_id == tenant_id, GroupModel.id == group_id
                )
            )
            if row: await session.delete(row)

    async def list_group_members(
        self, tenant_id: UUID, group_id: UUID
    ) -> list[dict[str, Any]]:
        async with self._sf() as session:
            rows = await session.scalars(
                select(GroupMemberModel).where(
                    GroupMemberModel.tenant_id == tenant_id,
                    GroupMemberModel.group_id == group_id,
                )
            )
            return [_gm_dict(r) for r in rows]

    async def add_group_member(
        self, tenant_id: UUID, group_id: UUID, membership_id: UUID
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            # Resolve principal from membership
            member = await session.scalar(
                select(MembershipModel).where(
                    MembershipModel.tenant_id == tenant_id,
                    MembershipModel.id == membership_id,
                )
            )
            if member is None:
                raise ValueError("membership not found")
            model = GroupMemberModel(
                tenant_id=tenant_id, group_id=group_id,
                principal_id=member.principal_id,
            )
            session.add(model)
            await session.flush()
            return _gm_dict(model)

    async def remove_group_member(
        self, tenant_id: UUID, group_id: UUID, membership_id: UUID
    ) -> None:
        async with self._sf.begin() as session:
            member = await session.scalar(
                select(MembershipModel).where(
                    MembershipModel.tenant_id == tenant_id,
                    MembershipModel.id == membership_id,
                )
            )
            if member is None:
                return
            row = await session.scalar(
                select(GroupMemberModel).where(
                    GroupMemberModel.tenant_id == tenant_id,
                    GroupMemberModel.group_id == group_id,
                    GroupMemberModel.principal_id == member.principal_id,
                )
            )
            if row: await session.delete(row)

    # ── Roles ─────────────────────────────────────────────────────────────

    async def list_roles(
        self, tenant_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        async with self._sf() as session:
            stmt = select(RoleModel).where(
                RoleModel.tenant_id == tenant_id
            ).order_by(RoleModel.name).limit(limit + 1)
            if cursor:
                stmt = stmt.where(RoleModel.id > UUID(cursor))
            rows = (await session.scalars(stmt)).all()
            items = [_role_dict(r) for r in rows[:limit]]
            next_cursor = str(rows[limit].id) if len(rows) > limit else None
            return items, next_cursor

    async def get_role(self, tenant_id: UUID, role_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(RoleModel).where(
                    RoleModel.tenant_id == tenant_id, RoleModel.id == role_id
                )
            )
            return _role_dict(row) if row else None

    async def create_role(
        self, tenant_id: UUID, name: str, description: str | None, permissions: list[str]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            model = RoleModel(
                tenant_id=tenant_id, name=name, description=description,
            )
            session.add(model)
            await session.flush()
            return _role_dict(model)

    async def update_role(
        self, tenant_id: UUID, role_id: UUID, name: str | None,
        description: str | None, permissions: list[str] | None,
    ) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(RoleModel).where(
                    RoleModel.tenant_id == tenant_id, RoleModel.id == role_id
                ).with_for_update()
            )
            if row is None:
                return None
            if name: row.name = name
            if description: row.description = description
            await session.flush()
            return _role_dict(row)

    # ── Role Bindings ─────────────────────────────────────────────────────

    async def list_role_bindings(
        self, tenant_id: UUID, principal_id: str | None = None,
        limit: int = 50, cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        async with self._sf() as session:
            stmt = select(RoleBindingModel).where(
                RoleBindingModel.tenant_id == tenant_id,
                RoleBindingModel.revoked_at.is_(None),
            ).order_by(RoleBindingModel.created_at.desc()).limit(limit + 1)
            if principal_id:
                stmt = stmt.where(RoleBindingModel.principal_id == UUID(principal_id))
            if cursor:
                stmt = stmt.where(RoleBindingModel.id > UUID(cursor))
            rows = (await session.scalars(stmt)).all()
            items = [_binding_dict(r) for r in rows[:limit]]
            next_cursor = str(rows[limit].id) if len(rows) > limit else None
            return items, next_cursor

    async def get_role_binding(self, tenant_id: UUID, binding_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(RoleBindingModel).where(
                    RoleBindingModel.tenant_id == tenant_id,
                    RoleBindingModel.id == binding_id,
                )
            )
            return _binding_dict(row) if row else None

    async def create_role_binding(
        self, tenant_id: UUID, principal_id: UUID, role_id: UUID, effect: str,
        storage_space_id: str | None, canonical_prefix: str | None,
        reason: str, expires_at: datetime, created_by: UUID,
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            model = RoleBindingModel(
                tenant_id=tenant_id, principal_id=principal_id, role_id=role_id,
                effect=effect, storage_space_id=UUID(storage_space_id) if storage_space_id else None,
                canonical_prefix=canonical_prefix, reason=reason,
                expires_at=expires_at, created_by_principal_id=created_by,
            )
            session.add(model)
            await session.flush()
            return _binding_dict(model)

    async def revoke_role_binding(self, tenant_id: UUID, binding_id: UUID) -> dict[str, Any] | None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(RoleBindingModel).where(
                    RoleBindingModel.tenant_id == tenant_id,
                    RoleBindingModel.id == binding_id,
                ).with_for_update()
            )
            if row is None:
                return None
            row.revoked_at = datetime.now(UTC)
            await session.flush()
            return _binding_dict(row)


def _membership_dict(m: MembershipModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "principal_id": str(m.principal_id), "user_id": str(m.user_id),
        "status": m.status.value if hasattr(m.status, 'value') else m.status,
        "authorization_version": m.authorization_version,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        "created_at": m.created_at.isoformat(),
    }


def _group_dict(m: GroupModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "name": m.name, "description": m.description,
        "enabled": m.enabled, "created_at": m.created_at.isoformat(),
    }


def _gm_dict(m: GroupMemberModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "group_id": str(m.group_id), "principal_id": str(m.principal_id),
        "created_at": m.created_at.isoformat(),
    }


def _role_dict(m: RoleModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "name": m.name, "description": m.description,
        "built_in": m.built_in, "created_at": m.created_at.isoformat(),
    }


def _binding_dict(m: RoleBindingModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "principal_id": str(m.principal_id), "role_id": str(m.role_id),
        "effect": m.effect.value if hasattr(m.effect, 'value') else m.effect,
        "storage_space_id": str(m.storage_space_id) if m.storage_space_id else None,
        "canonical_prefix": m.canonical_prefix,
        "reason": m.reason, "starts_at": m.starts_at.isoformat() if m.starts_at else None,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        "revoked_at": m.revoked_at.isoformat() if m.revoked_at else None,
        "created_at": m.created_at.isoformat(),
    }


def _principal_dict(m: PrincipalModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "type": m.type.value if hasattr(m.type, 'value') else m.type,
        "display_name": m.display_name, "enabled": m.enabled,
        "created_at": m.created_at.isoformat(),
    }