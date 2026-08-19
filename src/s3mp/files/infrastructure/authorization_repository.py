"""Read model used by file commands to evaluate tenant-scoped role bindings."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.applications.infrastructure.models import (
    ApplicationMembershipBindingModel,
    ApplicationModel,
)
from s3mp.authorization.domain.evaluator import Binding, Decision
from s3mp.authorization.infrastructure.models import (
    GroupMemberModel,
    GroupModel,
    PermissionModel,
    RoleBindingModel,
    RolePermissionModel,
)
from s3mp.identity.infrastructure.models import MembershipModel, PrincipalModel, UserModel
from s3mp.tenant.infrastructure.models import TenantModel


class SqlAlchemyFileAuthorizationStore:
    """Load active direct and representative-derived tenant bindings."""

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
        subject_principals: list[UUID] = [] if subject_kind == "application" else [principal_id]
        async with self._sf() as session:
            if subject_kind == "human":
                group_principals = await session.scalars(
                    select(GroupModel.principal_id)
                    .join(GroupMemberModel, GroupMemberModel.group_id == GroupModel.id)
                    .join(
                        PrincipalModel,
                        (PrincipalModel.tenant_id == GroupMemberModel.tenant_id)
                        & (PrincipalModel.id == GroupMemberModel.principal_id),
                    )
                    .where(
                        GroupModel.tenant_id == tenant_id,
                        GroupModel.enabled.is_(True),
                        GroupMemberModel.tenant_id == tenant_id,
                        GroupMemberModel.principal_id == principal_id,
                        PrincipalModel.enabled.is_(True),
                    )
                )
                subject_principals.extend(group_principals.all())
            elif subject_kind == "application":
                # An application remains the authenticated principal. Its one
                # tenant-local membership representative contributes permission
                # sources, but never replaces the application identity.
                representative = await session.execute(
                    select(MembershipModel.principal_id)
                    .join(
                        ApplicationMembershipBindingModel,
                        (ApplicationMembershipBindingModel.tenant_id == MembershipModel.tenant_id)
                        & (
                            ApplicationMembershipBindingModel.membership_id
                            == MembershipModel.id
                        ),
                    )
                    .join(
                        ApplicationModel,
                        (ApplicationModel.tenant_id == ApplicationMembershipBindingModel.tenant_id)
                        & (ApplicationModel.id == ApplicationMembershipBindingModel.application_id),
                    )
                    .join(
                        PrincipalModel,
                        (PrincipalModel.tenant_id == MembershipModel.tenant_id)
                        & (PrincipalModel.id == MembershipModel.principal_id),
                    )
                    .join(UserModel, UserModel.id == MembershipModel.user_id)
                    .join(TenantModel, TenantModel.id == MembershipModel.tenant_id)
                    .where(
                        ApplicationModel.tenant_id == tenant_id,
                        ApplicationModel.principal_id == principal_id,
                        ApplicationModel.status == "active",
                        ApplicationMembershipBindingModel.status == "active",
                        MembershipModel.status == "active",
                        MembershipModel.expires_at.is_(None)
                        | (MembershipModel.expires_at > now),
                        PrincipalModel.enabled.is_(True),
                        UserModel.status == "active",
                        TenantModel.status == "active",
                    )
                )
                representative_principal = representative.scalar_one_or_none()
                if representative_principal is not None:
                    subject_principals.append(representative_principal)
                    group_principals = await session.scalars(
                        select(GroupModel.principal_id)
                        .join(GroupMemberModel, GroupMemberModel.group_id == GroupModel.id)
                        .join(
                            PrincipalModel,
                            (PrincipalModel.tenant_id == GroupMemberModel.tenant_id)
                            & (PrincipalModel.id == GroupMemberModel.principal_id),
                        )
                        .where(
                            GroupModel.tenant_id == tenant_id,
                            GroupModel.enabled.is_(True),
                            GroupMemberModel.tenant_id == tenant_id,
                            GroupMemberModel.principal_id == representative_principal,
                            PrincipalModel.enabled.is_(True),
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
                    # File operations always require an application-bound
                    # storage-space scope. Legacy tenant-wide bindings remain
                    # in the database as audit evidence, but cannot authorize
                    # an object in a shared bucket.
                    RoleBindingModel.storage_space_id == storage_space_id,
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
