"""Database reads and writes for global platform authority."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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

    async def list_platform_tenants(self) -> list[dict[str, object]]:
        async with self.session_factory() as session:
            tenants = (await session.scalars(select(TenantModel).order_by(TenantModel.name))).all()
            return [self._tenant_summary(tenant) for tenant in tenants]

    async def get_platform_tenant(self, tenant_id: UUID) -> dict[str, object] | None:
        async with self.session_factory() as session:
            tenant = await session.get(TenantModel, tenant_id)
            return self._tenant_summary(tenant) if tenant else None

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
            request_ids = list(
                (
                    await session.scalars(statement)
                ).all()
            )
        for request_id in request_ids:
            await self.revoke_support_access(actor_user_id=None, request_id=request_id)
        return len(request_ids)

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
        self, *, email: str, display_name: str, password_hash: str
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
