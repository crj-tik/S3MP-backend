"""Read model used by file commands to evaluate tenant-scoped role bindings."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.authorization.domain.evaluator import Binding, Decision
from s3mp.authorization.infrastructure.models import (
    GroupMemberModel,
    GroupModel,
    PermissionModel,
    RoleBindingModel,
    RolePermissionModel,
)


class SqlAlchemyFileAuthorizationStore:
    """Load active direct and (for humans only) group-derived bindings."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def bindings_for(
        self,
        tenant_id: UUID,
        principal_id: UUID,
        storage_space_id: UUID,
        *,
        subject_kind: str = "human",
    ) -> list[Binding]:
        now = datetime.now(UTC)
        subject_principals = [principal_id]
        async with self._sf() as session:
            if subject_kind == "human":
                group_principals = await session.scalars(
                    select(GroupModel.principal_id)
                    .join(GroupMemberModel, GroupMemberModel.group_id == GroupModel.id)
                    .where(
                        GroupModel.tenant_id == tenant_id,
                        GroupModel.enabled.is_(True),
                        GroupMemberModel.tenant_id == tenant_id,
                        GroupMemberModel.principal_id == principal_id,
                    )
                )
                subject_principals.extend(group_principals.all())
            rows = await session.execute(
                select(RoleBindingModel, PermissionModel.name)
                .join(RolePermissionModel, RolePermissionModel.role_id == RoleBindingModel.role_id)
                .join(PermissionModel, PermissionModel.id == RolePermissionModel.permission_id)
                .where(
                    RoleBindingModel.tenant_id == tenant_id,
                    RoleBindingModel.principal_id.in_(subject_principals),
                    RoleBindingModel.revoked_at.is_(None),
                    RoleBindingModel.starts_at <= now,
                    RoleBindingModel.expires_at > now,
                    or_(
                        RoleBindingModel.storage_space_id.is_(None),
                        RoleBindingModel.storage_space_id == storage_space_id,
                    ),
                )
            )
        return [
            Binding(
                id=binding.id,
                permission=permission,
                effect=Decision(binding.effect),
                canonical_prefix=binding.canonical_prefix,
                starts_at=binding.starts_at,
                expires_at=binding.expires_at,
                reason=binding.reason,
            )
            for binding, permission in rows
        ]
