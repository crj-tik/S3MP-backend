"""Database reads and writes for global platform authority."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from s3mp.authorization.infrastructure.models import BindingEffect, RoleBindingModel
from s3mp.identity.application.security import PasswordCredential
from s3mp.identity.infrastructure.models import (
    MembershipModel,
    MembershipStatus,
    PrincipalModel,
    PrincipalType,
    SessionModel,
    UserModel,
    UserStatus,
)
from s3mp.platform.application.baseline import ensure_support_role, ensure_tenant_admin_role
from s3mp.platform.infrastructure.models import (
    PlatformAuditEventModel,
    PlatformBootstrapStateModel,
    PlatformRoleBindingModel,
    PlatformRoleModel,
    SupportAccessRequestModel,
    TenantLifecycleStatus,
)
from s3mp.tenant.infrastructure.models import TenantModel

if TYPE_CHECKING:
    from s3mp.platform.domain.context import PlatformContext


@dataclass(slots=True)
class SqlAlchemyPlatformStore:
    session_factory: async_sessionmaker[AsyncSession]

    async def find_by_normalized_email(self, normalized_email: str) -> PasswordCredential | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(UserModel).where(
                    UserModel.normalized_email == normalized_email,
                    UserModel.status == UserStatus.ACTIVE,
                )
            )
            if row is None:
                return None
            return PasswordCredential(user_id=row.id, password_hash=row.password_hash)

    async def find_by_identifier(self, identifier: str) -> PasswordCredential | None:
        """Resolve either the normalized email or normalized employee number."""
        async with self.session_factory() as session:
            identity_column = (
                UserModel.normalized_email
                if "@" in identifier
                else UserModel.normalized_employee_number
            )
            statement = select(UserModel).where(
                identity_column == identifier,
                UserModel.status == UserStatus.ACTIVE,
            )
            row = await session.scalar(statement)
            if row is None:
                return None
            return PasswordCredential(user_id=row.id, password_hash=row.password_hash)

    async def create_account(
        self,
        *,
        email: str,
        normalized_email: str,
        employee_number: str,
        normalized_employee_number: str,
        display_name: str,
        password_hash: str,
    ) -> dict[str, object]:
        async with self.session_factory.begin() as session:
            user = UserModel(
                email=email,
                normalized_email=normalized_email,
                employee_number=employee_number,
                normalized_employee_number=normalized_employee_number,
                display_name=display_name,
                status=UserStatus.ACTIVE,
                password_hash=password_hash,
            )
            session.add(user)
            await session.flush()
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=None,
                    action="platform.account_registered",
                    resource_type="user_account",
                    resource_id=str(user.id),
                    details={"registration": "public"},
                )
            )
            return {
                "id": str(user.id),
                "email": user.email,
                "employee_number": user.employee_number,
                "display_name": user.display_name,
            }

    async def create_account_session(
        self, user_id: UUID, token_digest: bytes, csrf_digest: bytes, expires_at: datetime
    ) -> UUID:
        from s3mp.platform.infrastructure.models import AccountSessionModel

        async with self.session_factory.begin() as session:
            row = AccountSessionModel(
                user_id=user_id,
                token_digest=token_digest,
                csrf_digest=csrf_digest,
                expires_at=expires_at,
            )
            session.add(row)
            await session.flush()
            return row.id

    async def resolve_account_session(self, token_digest: bytes) -> "PlatformContext | None":
        from s3mp.platform.domain.context import PlatformContext
        from s3mp.platform.infrastructure.models import AccountSessionModel

        now = datetime.now(UTC)
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AccountSessionModel).where(AccountSessionModel.token_digest == token_digest)
            )
            if row is None or row.revoked_at is not None or row.expires_at <= now:
                return None
            user = await session.get(UserModel, row.user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                return None
            permissions = await self._effective_permissions_in_session(session, user.id, now)
            return PlatformContext(user.id, row.id, permissions)

    async def revoke_account_session(self, session_id: UUID) -> None:
        from s3mp.platform.infrastructure.models import AccountSessionModel

        async with self.session_factory.begin() as session:
            await session.execute(
                update(AccountSessionModel)
                .where(
                    AccountSessionModel.id == session_id, AccountSessionModel.revoked_at.is_(None)
                )
                .values(revoked_at=datetime.now(UTC))
            )

    async def account_summary(self, user_id: UUID) -> dict[str, object] | None:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            user = await session.get(UserModel, user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                return None
            rows = await session.execute(
                select(MembershipModel, TenantModel)
                .join(TenantModel, TenantModel.id == MembershipModel.tenant_id)
                .where(
                    MembershipModel.user_id == user_id,
                    MembershipModel.status == MembershipStatus.ACTIVE,
                    TenantModel.status == TenantLifecycleStatus.ACTIVE,
                    (MembershipModel.expires_at.is_(None)) | (MembershipModel.expires_at > now),
                )
                .order_by(TenantModel.name)
            )
            return {
                "account": {
                    "id": str(user.id),
                    "email": user.email,
                    "employee_number": user.employee_number,
                    "display_name": user.display_name,
                },
                "tenants": [
                    {"id": str(tenant.id), "name": tenant.name, "slug": tenant.slug}
                    for _membership, tenant in rows
                ],
            }

    async def create_tenant_session(
        self,
        user_id: UUID,
        tenant_id: UUID,
        token_digest: bytes,
        csrf_digest: bytes,
        expires_at: datetime,
    ) -> bool:
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            membership = await session.scalar(
                select(MembershipModel)
                .join(TenantModel, TenantModel.id == MembershipModel.tenant_id)
                .where(
                    MembershipModel.user_id == user_id,
                    MembershipModel.tenant_id == tenant_id,
                    MembershipModel.status == MembershipStatus.ACTIVE,
                    TenantModel.status == TenantLifecycleStatus.ACTIVE,
                    (MembershipModel.expires_at.is_(None)) | (MembershipModel.expires_at > now),
                )
            )
            if membership is None:
                return False
            session.add(
                SessionModel(
                    tenant_id=membership.tenant_id,
                    membership_id=membership.id,
                    principal_id=membership.principal_id,
                    token_digest=token_digest,
                    csrf_digest=csrf_digest,
                    authorization_version=membership.authorization_version,
                    expires_at=expires_at,
                )
            )
            return True

    async def effective_permissions(
        self, user_id: UUID, *, now: datetime | None = None
    ) -> frozenset[str]:
        current = now or datetime.now(UTC)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(PlatformRoleModel.permissions)
                    .join(PlatformRoleBindingModel)
                    .where(
                        PlatformRoleBindingModel.user_id == user_id,
                        PlatformRoleBindingModel.revoked_at.is_(None),
                        (PlatformRoleBindingModel.expires_at.is_(None))
                        | (PlatformRoleBindingModel.expires_at > current),
                    )
                )
            ).scalars()
            return frozenset(permission for permissions in rows for permission in permissions)

    async def _effective_permissions_in_session(
        self, session: AsyncSession, user_id: UUID, now: datetime
    ) -> frozenset[str]:
        rows = (
            await session.execute(
                select(PlatformRoleModel.permissions)
                .join(PlatformRoleBindingModel)
                .where(
                    PlatformRoleBindingModel.user_id == user_id,
                    PlatformRoleBindingModel.revoked_at.is_(None),
                    (PlatformRoleBindingModel.expires_at.is_(None))
                    | (PlatformRoleBindingModel.expires_at > now),
                )
            )
        ).scalars()
        return frozenset(permission for permissions in rows for permission in permissions)

    async def create_audit_event(
        self,
        *,
        actor_user_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: str | None,
        details: dict[str, object],
    ) -> None:
        async with self.session_factory.begin() as session:
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=actor_user_id,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    details=details,
                )
            )

    async def list_platform_tenants(
        self, *, limit: int, cursor: UUID | None, include_deleted: bool = False
    ) -> tuple[list[dict[str, object]], UUID | None]:
        async with self.session_factory() as session:
            statement = select(TenantModel).order_by(TenantModel.id).limit(limit + 1)
            if not include_deleted:
                statement = statement.where(TenantModel.status != TenantLifecycleStatus.DELETED)
            if cursor is not None:
                statement = statement.where(TenantModel.id > cursor)
            rows = list((await session.scalars(statement)).all())
            page = rows[:limit]
            return [self._tenant_summary(tenant) for tenant in page], (
                page[-1].id if len(rows) > limit else None
            )

    async def get_platform_tenant(self, tenant_id: UUID) -> dict[str, object] | None:
        async with self.session_factory() as session:
            tenant = await session.scalar(
                select(TenantModel).where(
                    TenantModel.id == tenant_id,
                    TenantModel.status != TenantLifecycleStatus.DELETED,
                )
            )
            return self._tenant_summary(tenant) if tenant else None

    async def list_platform_accounts(
        self,
        *,
        limit: int,
        cursor: UUID | None,
        query: str | None,
        status: str | None,
        include_deleted: bool = False,
    ) -> tuple[list[dict[str, object]], UUID | None]:
        async with self.session_factory() as session:
            statement = select(UserModel).order_by(UserModel.id).limit(limit + 1)
            if not include_deleted:
                statement = statement.where(UserModel.status != UserStatus.DELETED)
            if cursor is not None:
                statement = statement.where(UserModel.id > cursor)
            if status is not None:
                statement = statement.where(UserModel.status == UserStatus(status))
            if query:
                normalized_query = query.strip().casefold()
                statement = statement.where(
                    or_(
                        UserModel.normalized_email == normalized_query,
                        UserModel.normalized_employee_number == normalized_query,
                        UserModel.display_name.ilike(f"%{query.strip()}%"),
                    )
                )
            rows = list((await session.scalars(statement)).all())
            page = rows[:limit]
            return [self._account_summary(row) for row in page], (
                page[-1].id if len(rows) > limit else None
            )

    async def get_platform_account(self, user_id: UUID) -> dict[str, object] | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(UserModel).where(
                    UserModel.id == user_id, UserModel.status != UserStatus.DELETED
                )
            )
            return self._account_summary(row) if row else None

    async def delete_platform_account(
        self, *, user_id: UUID, actor_user_id: UUID, reason: str
    ) -> dict[str, object] | None:
        from s3mp.platform.infrastructure.models import AccountSessionModel

        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await session.scalar(
                select(UserModel).where(UserModel.id == user_id).with_for_update()
            )
            if user is None or user.status == UserStatus.DELETED:
                return None
            previous_status = str(user.status)
            user.status = UserStatus.DELETED
            user.deleted_at = now
            user.deleted_by = actor_user_id
            user.deletion_reason = reason
            await session.execute(
                update(AccountSessionModel)
                .where(
                    AccountSessionModel.user_id == user_id, AccountSessionModel.revoked_at.is_(None)
                )
                .values(revoked_at=now)
            )
            await session.execute(
                update(SessionModel)
                .where(
                    SessionModel.membership_id.in_(
                        select(MembershipModel.id).where(MembershipModel.user_id == user_id)
                    ),
                    SessionModel.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await session.execute(
                update(MembershipModel)
                .where(MembershipModel.user_id == user_id)
                .values(
                    status=MembershipStatus.REMOVED,
                    authorization_version=MembershipModel.authorization_version + 1,
                )
            )
            await session.execute(
                update(PlatformRoleBindingModel)
                .where(
                    PlatformRoleBindingModel.user_id == user_id,
                    PlatformRoleBindingModel.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await session.execute(
                update(PrincipalModel)
                .where(
                    PrincipalModel.id.in_(
                        select(MembershipModel.principal_id).where(
                            MembershipModel.user_id == user_id
                        )
                    )
                )
                .values(enabled=False)
            )
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=actor_user_id,
                    action="platform.account_deleted",
                    resource_type="user_account",
                    resource_id=str(user_id),
                    details={"reason": reason, "previous_status": previous_status},
                )
            )
            await session.flush()
            return self._account_summary(user)

    async def restore_platform_account(
        self, *, user_id: UUID, actor_user_id: UUID, reason: str
    ) -> dict[str, object] | None:
        async with self.session_factory.begin() as session:
            user = await session.scalar(
                select(UserModel)
                .where(UserModel.id == user_id, UserModel.status == UserStatus.DELETED)
                .with_for_update()
            )
            if user is None:
                return None
            conflict = await session.scalar(
                select(UserModel.id).where(
                    UserModel.id != user_id,
                    UserModel.status != UserStatus.DELETED,
                    or_(
                        UserModel.normalized_email == user.normalized_email,
                        (UserModel.normalized_employee_number == user.normalized_employee_number)
                        if user.normalized_employee_number is not None
                        else False,
                    ),
                )
            )
            if conflict is not None:
                raise ValueError("account identity is already used by an active account")
            user.status = UserStatus.ACTIVE
            user.deleted_at = None
            user.deleted_by = None
            user.deletion_reason = None
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=actor_user_id,
                    action="platform.account_restored",
                    resource_type="user_account",
                    resource_id=str(user_id),
                    details={"reason": reason},
                )
            )
            await session.flush()
            return self._account_summary(user)

    async def list_platform_roles(
        self, *, limit: int, cursor: UUID | None
    ) -> tuple[list[dict[str, object]], UUID | None]:
        async with self.session_factory() as session:
            statement = select(PlatformRoleModel).order_by(PlatformRoleModel.id).limit(limit + 1)
            if cursor is not None:
                statement = statement.where(PlatformRoleModel.id > cursor)
            rows = list((await session.scalars(statement)).all())
            page = rows[:limit]
            return [self._role_summary(row) for row in page], (
                page[-1].id if len(rows) > limit else None
            )

    async def list_platform_role_bindings(
        self, *, limit: int, cursor: UUID | None
    ) -> tuple[list[dict[str, object]], UUID | None]:
        async with self.session_factory() as session:
            statement = (
                select(PlatformRoleBindingModel, PlatformRoleModel, UserModel)
                .join(PlatformRoleModel, PlatformRoleModel.id == PlatformRoleBindingModel.role_id)
                .join(UserModel, UserModel.id == PlatformRoleBindingModel.user_id)
                .where(UserModel.status != UserStatus.DELETED)
                .order_by(PlatformRoleBindingModel.id)
                .limit(limit + 1)
            )
            if cursor is not None:
                statement = statement.where(PlatformRoleBindingModel.id > cursor)
            rows = list((await session.execute(statement)).all())
            page = rows[:limit]
            return [self._role_binding_summary(*row) for row in page], (
                page[-1][0].id if len(rows) > limit else None
            )

    async def list_support_access(
        self, *, limit: int, cursor: UUID | None, status: str | None
    ) -> tuple[list[dict[str, object]], UUID | None]:
        async with self.session_factory() as session:
            now = datetime.now(UTC)
            approver = aliased(UserModel)
            statement = (
                select(SupportAccessRequestModel, UserModel, TenantModel, approver)
                .join(UserModel, UserModel.id == SupportAccessRequestModel.requester_user_id)
                .join(TenantModel, TenantModel.id == SupportAccessRequestModel.tenant_id)
                .outerjoin(approver, approver.id == SupportAccessRequestModel.approved_by_user_id)
                .where(TenantModel.status == TenantLifecycleStatus.ACTIVE)
                .order_by(SupportAccessRequestModel.id)
                .limit(limit + 1)
            )
            if cursor is not None:
                statement = statement.where(SupportAccessRequestModel.id > cursor)
            if status == "pending":
                statement = statement.where(
                    SupportAccessRequestModel.revoked_at.is_(None),
                    SupportAccessRequestModel.approved_at.is_(None),
                    SupportAccessRequestModel.expires_at > now,
                )
            elif status == "approved":
                statement = statement.where(
                    SupportAccessRequestModel.revoked_at.is_(None),
                    SupportAccessRequestModel.approved_at.is_not(None),
                    SupportAccessRequestModel.expires_at > now,
                )
            elif status == "revoked":
                statement = statement.where(SupportAccessRequestModel.revoked_at.is_not(None))
            elif status == "expired":
                statement = statement.where(
                    SupportAccessRequestModel.revoked_at.is_(None),
                    SupportAccessRequestModel.expires_at <= now,
                )
            elif status is not None:
                raise ValueError("unsupported support access status")
            rows = list((await session.execute(statement)).all())
            page = rows[:limit]
            return [self._support_read_summary(*row, now=now) for row in page], (
                page[-1][0].id if len(rows) > limit else None
            )

    async def get_support_access(self, request_id: UUID) -> dict[str, object] | None:
        async with self.session_factory() as session:
            approver = aliased(UserModel)
            row = await session.execute(
                select(SupportAccessRequestModel, UserModel, TenantModel, approver)
                .join(UserModel, UserModel.id == SupportAccessRequestModel.requester_user_id)
                .join(TenantModel, TenantModel.id == SupportAccessRequestModel.tenant_id)
                .outerjoin(approver, approver.id == SupportAccessRequestModel.approved_by_user_id)
                .where(
                    SupportAccessRequestModel.id == request_id,
                    TenantModel.status == TenantLifecycleStatus.ACTIVE,
                )
            )
            value = row.first()
            return self._support_read_summary(*value) if value else None

    async def list_platform_audit_events(
        self, *, limit: int, cursor: UUID | None, action: str | None
    ) -> tuple[list[dict[str, object]], UUID | None]:
        async with self.session_factory() as session:
            statement = (
                select(PlatformAuditEventModel)
                .order_by(PlatformAuditEventModel.id)
                .limit(limit + 1)
            )
            if cursor is not None:
                statement = statement.where(PlatformAuditEventModel.id > cursor)
            if action:
                statement = statement.where(PlatformAuditEventModel.action == action)
            rows = list((await session.scalars(statement)).all())
            page = rows[:limit]
            return [self._audit_summary(row) for row in page], (
                page[-1].id if len(rows) > limit else None
            )

    async def get_platform_audit_event(self, event_id: UUID) -> dict[str, object] | None:
        async with self.session_factory() as session:
            row = await session.get(PlatformAuditEventModel, event_id)
            return self._audit_summary(row) if row else None

    async def create_platform_tenant(
        self, *, slug: str, name: str, initial_admin_user_id: UUID, actor_user_id: UUID
    ) -> dict[str, object]:
        async with self.session_factory.begin() as session:
            user = await session.get(UserModel, initial_admin_user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                raise ValueError("initial administrator must be an active account")
            if await session.scalar(select(TenantModel.id).where(TenantModel.slug == slug)):
                raise ValueError("tenant slug already exists")
            tenant = TenantModel(slug=slug, name=name, status=TenantLifecycleStatus.ACTIVE)
            session.add(tenant)
            await session.flush()
            principal = PrincipalModel(
                tenant_id=tenant.id, type=PrincipalType.USER, display_name=user.display_name
            )
            session.add(principal)
            await session.flush()
            membership = MembershipModel(
                tenant_id=tenant.id,
                user_id=user.id,
                principal_id=principal.id,
                status=MembershipStatus.ACTIVE,
            )
            session.add(membership)
            await session.flush()
            role = await ensure_tenant_admin_role(session, tenant.id)
            session.add(
                RoleBindingModel(
                    tenant_id=tenant.id,
                    principal_id=principal.id,
                    role_id=role.id,
                    effect=BindingEffect.ALLOW,
                    storage_space_id=None,
                    canonical_prefix=None,
                    reason="initial tenant administrator",
                    expires_at=datetime.max.replace(tzinfo=UTC),
                    created_by_principal_id=principal.id,
                )
            )
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=actor_user_id,
                    action="platform.tenant_created",
                    resource_type="tenant",
                    resource_id=str(tenant.id),
                    details={"slug": tenant.slug, "initial_admin_user_id": str(user.id)},
                )
            )
            await session.flush()
            return self._tenant_summary(tenant)

    async def update_platform_tenant(
        self, *, tenant_id: UUID, name: str | None, status: str | None, actor_user_id: UUID
    ) -> dict[str, object] | None:
        async with self.session_factory.begin() as session:
            tenant = await session.get(TenantModel, tenant_id, with_for_update=True)
            if tenant is None:
                return None
            if tenant.status == TenantLifecycleStatus.DELETED:
                return None
            if name is not None:
                tenant.name = name
            if status is not None:
                tenant.status = TenantLifecycleStatus(status)
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=actor_user_id,
                    action="platform.tenant_updated",
                    resource_type="tenant",
                    resource_id=str(tenant.id),
                    details={"name_changed": name is not None, "status": status},
                )
            )
            await session.flush()
            return self._tenant_summary(tenant)

    async def delete_platform_tenant(
        self, *, tenant_id: UUID, actor_user_id: UUID, reason: str
    ) -> dict[str, object] | None:
        from s3mp.applications.infrastructure.models import ApiKeyModel, ApplicationModel
        from s3mp.files.infrastructure.models import (
            FileOperationModel,
            MultipartSessionModel,
            UploadSessionModel,
        )
        from s3mp.storage.infrastructure.models import StorageConnectionModel, StorageSpaceModel

        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            tenant = await session.scalar(
                select(TenantModel).where(TenantModel.id == tenant_id).with_for_update()
            )
            if tenant is None or tenant.status == TenantLifecycleStatus.DELETED:
                return None
            tenant.status = TenantLifecycleStatus.DELETED
            tenant.deleted_at = now
            tenant.deleted_by = actor_user_id
            tenant.deletion_reason = reason
            await session.execute(
                update(SessionModel)
                .where(SessionModel.tenant_id == tenant_id, SessionModel.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            await session.execute(
                update(MembershipModel)
                .where(
                    MembershipModel.tenant_id == tenant_id,
                    MembershipModel.status == MembershipStatus.ACTIVE,
                )
                .values(
                    status=MembershipStatus.REMOVED,
                    authorization_version=MembershipModel.authorization_version + 1,
                )
            )
            await session.execute(
                update(PrincipalModel)
                .where(PrincipalModel.tenant_id == tenant_id)
                .values(enabled=False)
            )
            await session.execute(
                update(RoleBindingModel)
                .where(
                    RoleBindingModel.tenant_id == tenant_id, RoleBindingModel.revoked_at.is_(None)
                )
                .values(revoked_at=now)
            )
            await session.execute(
                update(ApplicationModel)
                .where(
                    ApplicationModel.tenant_id == tenant_id, ApplicationModel.status != "deleted"
                )
                .values(
                    status="deleted",
                    deleted_at=now,
                    deleted_by=actor_user_id,
                    deletion_reason=reason,
                    authorization_version=ApplicationModel.authorization_version + 1,
                )
            )
            await session.execute(
                update(ApiKeyModel)
                .where(ApiKeyModel.tenant_id == tenant_id, ApiKeyModel.status == "active")
                .values(status="revoked", revoked_at=now)
            )
            await session.execute(
                update(StorageConnectionModel)
                .where(
                    StorageConnectionModel.tenant_id == tenant_id,
                    StorageConnectionModel.status == "active",
                )
                .values(status="disabled")
            )
            await session.execute(
                update(StorageSpaceModel)
                .where(
                    StorageSpaceModel.tenant_id == tenant_id, StorageSpaceModel.status == "active"
                )
                .values(status="deleting")
            )
            await session.execute(
                update(UploadSessionModel)
                .where(
                    UploadSessionModel.tenant_id == tenant_id,
                    UploadSessionModel.status == "pending",
                )
                .values(status="cancelled")
            )
            await session.execute(
                update(MultipartSessionModel)
                .where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.status == "pending",
                )
                .values(status="cancelled")
            )
            await session.execute(
                update(FileOperationModel)
                .where(
                    FileOperationModel.tenant_id == tenant_id,
                    FileOperationModel.status == "pending",
                )
                .values(status="cancelled", failure_reason="tenant_deleted")
            )
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=actor_user_id,
                    action="platform.tenant_deleted",
                    resource_type="tenant",
                    resource_id=str(tenant_id),
                    details={"reason": reason},
                )
            )
            await session.flush()
            return self._tenant_summary(tenant)

    async def restore_platform_tenant(
        self, *, tenant_id: UUID, actor_user_id: UUID, reason: str
    ) -> dict[str, object] | None:
        async with self.session_factory.begin() as session:
            tenant = await session.scalar(
                select(TenantModel)
                .where(
                    TenantModel.id == tenant_id, TenantModel.status == TenantLifecycleStatus.DELETED
                )
                .with_for_update()
            )
            if tenant is None:
                return None
            tenant.status = TenantLifecycleStatus.SUSPENDED
            tenant.deleted_at = None
            tenant.deleted_by = None
            tenant.deletion_reason = None
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=actor_user_id,
                    action="platform.tenant_restored",
                    resource_type="tenant",
                    resource_id=str(tenant_id),
                    details={"reason": reason, "restored_status": "suspended"},
                )
            )
            await session.flush()
            return self._tenant_summary(tenant)

    async def grant_platform_role(
        self, *, actor_user_id: UUID, user_id: UUID, role_name: str, expires_at: datetime | None
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            user = await session.get(UserModel, user_id)
            role = await session.scalar(
                select(PlatformRoleModel).where(PlatformRoleModel.name == role_name)
            )
            if user is None or user.status != UserStatus.ACTIVE:
                raise ValueError("platform role recipient must be an active account")
            if role is None:
                raise ValueError("unknown platform role")
            existing = await session.scalar(
                select(PlatformRoleBindingModel).where(
                    PlatformRoleBindingModel.user_id == user_id,
                    PlatformRoleBindingModel.role_id == role.id,
                    PlatformRoleBindingModel.revoked_at.is_(None),
                    (PlatformRoleBindingModel.expires_at.is_(None))
                    | (PlatformRoleBindingModel.expires_at > now),
                )
            )
            if existing is not None:
                raise ValueError("active platform role binding already exists")
            binding = PlatformRoleBindingModel(
                user_id=user_id, role_id=role.id, expires_at=expires_at
            )
            session.add(binding)
            await session.flush()
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=actor_user_id,
                    action="platform.role_granted",
                    resource_type="platform_role_binding",
                    resource_id=str(binding.id),
                    details={
                        "role": role.name,
                        "user_id": str(user_id),
                        "expires_at": str(expires_at),
                    },
                )
            )
            return {
                "id": str(binding.id),
                "user_id": str(user_id),
                "role": role.name,
                "expires_at": expires_at.isoformat() if expires_at else None,
            }

    async def revoke_platform_role(self, *, actor_user_id: UUID, binding_id: UUID) -> bool:
        async with self.session_factory.begin() as session:
            binding = await session.get(PlatformRoleBindingModel, binding_id, with_for_update=True)
            if binding is None or binding.revoked_at is not None:
                return False
            role = await session.get(PlatformRoleModel, binding.role_id)
            binding.revoked_at = datetime.now(UTC)
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=actor_user_id,
                    action="platform.role_revoked",
                    resource_type="platform_role_binding",
                    resource_id=str(binding.id),
                    details={
                        "role": role.name if role else "unknown",
                        "user_id": str(binding.user_id),
                    },
                )
            )
            return True

    async def request_support_access(
        self, *, requester_user_id: UUID, tenant_id: UUID, reason: str, expires_at: datetime
    ) -> dict[str, object]:
        if expires_at <= datetime.now(UTC):
            raise ValueError("support access expiry must be in the future")
        async with self.session_factory.begin() as session:
            if await session.get(TenantModel, tenant_id) is None:
                raise ValueError("tenant not found")
            row = SupportAccessRequestModel(
                requester_user_id=requester_user_id,
                tenant_id=tenant_id,
                reason=reason,
                expires_at=expires_at,
            )
            session.add(row)
            await session.flush()
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=requester_user_id,
                    action="platform.support_access_requested",
                    resource_type="support_access_request",
                    resource_id=str(row.id),
                    details={"tenant_id": str(tenant_id), "expires_at": expires_at.isoformat()},
                )
            )
            return self._support_summary(row)

    async def approve_support_access(
        self, *, approver_user_id: UUID, request_id: UUID
    ) -> dict[str, object] | None:
        now = datetime.now(UTC)
        async with self.session_factory.begin() as session:
            request = await session.get(SupportAccessRequestModel, request_id, with_for_update=True)
            if request is None:
                return None
            if request.requester_user_id == approver_user_id:
                raise ValueError("support access requires a different approver")
            if (
                request.approved_at is not None
                or request.revoked_at is not None
                or request.expires_at <= now
            ):
                raise ValueError("support access request is no longer approvable")
            user = await session.get(UserModel, request.requester_user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                raise ValueError("requester account is not active")
            if await session.scalar(
                select(MembershipModel.id).where(
                    MembershipModel.tenant_id == request.tenant_id,
                    MembershipModel.user_id == request.requester_user_id,
                )
            ):
                raise ValueError("requester already has a tenant membership")
            principal = PrincipalModel(
                tenant_id=request.tenant_id, type=PrincipalType.USER, display_name=user.display_name
            )
            session.add(principal)
            await session.flush()
            membership = MembershipModel(
                tenant_id=request.tenant_id,
                user_id=user.id,
                principal_id=principal.id,
                status=MembershipStatus.ACTIVE,
                expires_at=request.expires_at,
            )
            session.add(membership)
            await session.flush()
            role = await ensure_support_role(session, request.tenant_id)
            binding = RoleBindingModel(
                tenant_id=request.tenant_id,
                principal_id=principal.id,
                role_id=role.id,
                effect=BindingEffect.ALLOW,
                storage_space_id=None,
                canonical_prefix=None,
                reason="approved platform support access",
                expires_at=request.expires_at,
                created_by_principal_id=principal.id,
            )
            session.add(binding)
            await session.flush()
            request.approved_at = now
            request.approved_by_user_id = approver_user_id
            request.membership_id = membership.id
            request.role_binding_id = binding.id
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=approver_user_id,
                    action="platform.support_access_approved",
                    resource_type="support_access_request",
                    resource_id=str(request.id),
                    details={
                        "tenant_id": str(request.tenant_id),
                        "file_content_permissions": False,
                    },
                )
            )
            return self._support_summary(request)

    async def revoke_support_access(self, *, actor_user_id: UUID | None, request_id: UUID) -> bool:
        async with self.session_factory.begin() as session:
            request = await session.get(SupportAccessRequestModel, request_id, with_for_update=True)
            if request is None or request.revoked_at is not None:
                return False
            request.revoked_at = datetime.now(UTC)
            if request.role_binding_id:
                await session.execute(
                    update(RoleBindingModel)
                    .where(RoleBindingModel.id == request.role_binding_id)
                    .values(revoked_at=request.revoked_at)
                )
            if request.membership_id:
                await session.execute(
                    update(MembershipModel)
                    .where(MembershipModel.id == request.membership_id)
                    .values(
                        status=MembershipStatus.SUSPENDED,
                        authorization_version=MembershipModel.authorization_version + 1,
                    )
                )
                await session.execute(
                    update(SessionModel)
                    .where(
                        SessionModel.membership_id == request.membership_id,
                        SessionModel.revoked_at.is_(None),
                    )
                    .values(revoked_at=request.revoked_at)
                )
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=actor_user_id,
                    action="platform.support_access_revoked",
                    resource_type="support_access_request",
                    resource_id=str(request.id),
                    details={},
                )
            )
            return True

    async def expire_support_access(
        self, *, now: datetime, request_ids: Sequence[UUID] | None = None
    ) -> int:
        """Revoke elapsed support grants, optionally limited to known request IDs.

        The optional filter keeps maintenance callers global while allowing a
        deterministic repository-level verification without touching unrelated
        expired support grants in a shared development database.
        """
        async with self.session_factory() as session:
            statement = select(SupportAccessRequestModel.id).where(
                SupportAccessRequestModel.approved_at.is_not(None),
                SupportAccessRequestModel.revoked_at.is_(None),
                SupportAccessRequestModel.expires_at <= now,
            )
            if request_ids is not None:
                statement = statement.where(SupportAccessRequestModel.id.in_(request_ids))
            request_ids = list((await session.scalars(statement)).all())
        for request_id in request_ids:
            await self.revoke_support_access(actor_user_id=None, request_id=request_id)
        return len(request_ids)

    @staticmethod
    def _account_summary(row: UserModel) -> dict[str, object]:
        return {
            "id": row.id,
            "email": row.email,
            "employee_number": row.employee_number,
            "display_name": row.display_name,
            "status": row.status.value,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "deleted_at": row.deleted_at,
            "deleted_by": row.deleted_by,
            "deletion_reason": row.deletion_reason,
        }

    @staticmethod
    def _role_summary(row: PlatformRoleModel) -> dict[str, object]:
        return {
            "id": row.id,
            "name": row.name,
            "permissions": row.permissions,
            "built_in": row.built_in,
            "created_at": row.created_at,
        }

    @staticmethod
    def _role_binding_summary(
        binding: PlatformRoleBindingModel, role: PlatformRoleModel, user: UserModel
    ) -> dict[str, object]:
        return {
            "id": binding.id,
            "user": SqlAlchemyPlatformStore._account_summary(user),
            "role": SqlAlchemyPlatformStore._role_summary(role),
            "expires_at": binding.expires_at,
            "revoked_at": binding.revoked_at,
            "created_at": binding.created_at,
        }

    @staticmethod
    def _support_read_summary(
        row: SupportAccessRequestModel,
        requester: UserModel,
        tenant: TenantModel,
        approver: UserModel | None,
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        now = now or datetime.now(UTC)
        status = (
            "revoked"
            if row.revoked_at
            else "expired"
            if row.expires_at <= now
            else "approved"
            if row.approved_at
            else "pending"
        )
        return {
            "id": row.id,
            "requester": SqlAlchemyPlatformStore._account_summary(requester),
            "approver": SqlAlchemyPlatformStore._account_summary(approver) if approver else None,
            "tenant": SqlAlchemyPlatformStore._tenant_summary(tenant),
            "reason": row.reason,
            "status": status,
            "expires_at": row.expires_at,
            "approved_at": row.approved_at,
            "approved_by_user_id": row.approved_by_user_id,
            "membership_id": row.membership_id,
            "role_binding_id": row.role_binding_id,
            "revoked_at": row.revoked_at,
            "created_at": row.created_at,
        }

    @staticmethod
    def _audit_summary(row: PlatformAuditEventModel) -> dict[str, object]:
        return {
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "details": row.details,
            "created_at": row.created_at,
        }

    @staticmethod
    def _support_summary(row: SupportAccessRequestModel) -> dict[str, object]:
        return {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "expires_at": row.expires_at.isoformat(),
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        }

    @staticmethod
    def _tenant_summary(tenant: TenantModel) -> dict[str, object]:
        return {
            "id": str(tenant.id),
            "slug": tenant.slug,
            "name": tenant.name,
            "status": tenant.status.value,
            "created_at": tenant.created_at,
            "deleted_at": tenant.deleted_at,
            "deleted_by": tenant.deleted_by,
            "deletion_reason": tenant.deletion_reason,
        }

    async def active_platform_admin_exists(self) -> bool:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(PlatformRoleBindingModel.id)
                .join(PlatformRoleModel)
                .join(UserModel)
                .where(
                    PlatformRoleModel.name == "platform_admin",
                    PlatformRoleBindingModel.revoked_at.is_(None),
                    UserModel.status == UserStatus.ACTIVE,
                )
                .limit(1)
            )
            return row is not None

    async def create_initial_platform_admin(
        self, *, email: str, employee_number: str, display_name: str, password_hash: str
    ) -> UUID:
        """Atomically create the first administrator or fail if one already exists."""
        async with self.session_factory.begin() as session:
            state = await session.get(PlatformBootstrapStateModel, True, with_for_update=True)
            if state is not None:
                raise ValueError("platform administrator already exists")
            session.add(PlatformBootstrapStateModel(singleton=True))
            await session.flush()
            role = await session.scalar(
                select(PlatformRoleModel).where(PlatformRoleModel.name == "platform_admin")
            )
            if role is None:
                raise ValueError("platform authorization baseline is not seeded")
            user = UserModel(
                email=email,
                normalized_email=email.strip().casefold(),
                employee_number=employee_number,
                normalized_employee_number=employee_number.strip().casefold(),
                display_name=display_name,
                status=UserStatus.ACTIVE,
                password_hash=password_hash,
            )
            session.add(user)
            await session.flush()
            session.add(PlatformRoleBindingModel(user_id=user.id, role_id=role.id))
            session.add(
                PlatformAuditEventModel(
                    actor_user_id=user.id,
                    action="platform.bootstrap_completed",
                    resource_type="platform_role_binding",
                    resource_id=None,
                    details={"role": "platform_admin"},
                )
            )
            return user.id
