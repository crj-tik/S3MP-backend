"""Tenant-scoped SQLAlchemy repositories for application lifecycle services."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.applications.infrastructure.models import (
    ApiKeyModel,
    ApplicationModel,
    ApplicationOwnerModel,
)
from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.identity.infrastructure.models import MembershipModel, PrincipalModel, PrincipalType


def _application(model: ApplicationModel) -> dict[str, object]:
    return {
        "id": str(model.id),
        "tenant_id": model.tenant_id,
        "principal_id": model.principal_id,
        "name": model.name,
        "status": model.status,
        "authorization_version": model.authorization_version,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }


def _api_key(model: ApiKeyModel) -> dict[str, object]:
    return {
        "id": str(model.id),
        "tenant_id": model.tenant_id,
        "application_id": str(model.application_id),
        "key_id": model.key_id,
        "secret_digest": model.secret_digest,
        "pepper_version": model.pepper_version,
        "scopes": list(model.scopes),
        "status": model.status,
        "expires_at": model.expires_at,
        "revoked_at": model.revoked_at,
        "last_used_at": model.last_used_at,
        "created_at": model.created_at,
    }


class SqlAlchemyApplicationStore:
    """Implements application and API-key ports with a fresh session per call."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def list_apps(
        self, tenant_id: UUID, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, object]], str | None]:
        async with self._sessions() as session:
            statement = select(ApplicationModel).where(ApplicationModel.tenant_id == tenant_id)
            if cursor:
                statement = statement.where(ApplicationModel.id > UUID(cursor))
            models = (
                await session.scalars(statement.order_by(ApplicationModel.id).limit(limit + 1))
            ).all()
        page, extra = models[:limit], len(models) > limit
        return [_application(item) for item in page], str(page[-1].id) if extra and page else None

    async def get_app(self, tenant_id: UUID, app_id: UUID) -> dict[str, object] | None:
        async with self._sessions() as session:
            model = await session.scalar(
                select(ApplicationModel).where(
                    ApplicationModel.tenant_id == tenant_id, ApplicationModel.id == app_id
                )
            )
        return _application(model) if model else None

    async def create_app(self, tenant_id: UUID, name: str, principal_id: UUID) -> dict[str, object]:
        async with self._sessions.begin() as session:
            application_principal = PrincipalModel(
                tenant_id=tenant_id,
                type=PrincipalType.APPLICATION,
                display_name=name,
                enabled=True,
            )
            session.add(application_principal)
            await session.flush()
            model = ApplicationModel(
                tenant_id=tenant_id,
                name=name,
                principal_id=application_principal.id,
                status="active",
            )
            session.add(model)
            await session.flush()
            session.add(
                ApplicationOwnerModel(
                    tenant_id=tenant_id, application_id=model.id, owner_principal_id=principal_id
                )
            )
            await session.flush()
            return _application(model)

    async def update_app(
        self, tenant_id: UUID, app_id: UUID, name: str | None
    ) -> dict[str, object] | None:
        async with self._sessions.begin() as session:
            model = await session.scalar(
                select(ApplicationModel)
                .where(ApplicationModel.tenant_id == tenant_id, ApplicationModel.id == app_id)
                .with_for_update()
            )
            if model is None:
                return None
            if name is not None:
                model.name = name
            await session.flush()
            return _application(model)

    async def takeover_app(
        self, tenant_id: UUID, app_id: UUID, owner_principal_id: UUID, reason: str
    ) -> dict[str, object] | None:
        """Atomically add the accountable owner and reactivate a contained app."""
        async with self._sessions.begin() as session:
            model = await session.scalar(
                select(ApplicationModel)
                .where(ApplicationModel.tenant_id == tenant_id, ApplicationModel.id == app_id)
                .with_for_update()
            )
            if model is None:
                return None
            if model.status != "pending_takeover":
                return _application(model)

            owner = await session.scalar(
                select(ApplicationOwnerModel).where(
                    ApplicationOwnerModel.tenant_id == tenant_id,
                    ApplicationOwnerModel.application_id == app_id,
                    ApplicationOwnerModel.owner_principal_id == owner_principal_id,
                )
            )
            if owner is None:
                session.add(
                    ApplicationOwnerModel(
                        tenant_id=tenant_id,
                        application_id=app_id,
                        owner_principal_id=owner_principal_id,
                    )
                )
            model.status = "active"
            model.authorization_version += 1
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=owner_principal_id,
                    action="application.taken_over",
                    resource_type="application",
                    resource_id=str(app_id),
                    details={"reason_code": reason},
                )
            )
            await session.flush()
            await session.refresh(model)
            return _application(model)

    async def list_owners(self, tenant_id: UUID, app_id: UUID) -> list[UUID]:
        async with self._sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(ApplicationOwnerModel.owner_principal_id).where(
                            ApplicationOwnerModel.tenant_id == tenant_id,
                            ApplicationOwnerModel.application_id == app_id,
                        )
                    )
                ).all()
            )

    async def list_owner_summaries(
        self, tenant_id: UUID, app_id: UUID
    ) -> list[dict[str, str]]:
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(ApplicationOwnerModel.owner_principal_id, PrincipalModel.type)
                    .join(
                        PrincipalModel,
                        and_(
                            PrincipalModel.tenant_id == ApplicationOwnerModel.tenant_id,
                            PrincipalModel.id == ApplicationOwnerModel.owner_principal_id,
                        ),
                    )
                    .where(
                        ApplicationOwnerModel.tenant_id == tenant_id,
                        ApplicationOwnerModel.application_id == app_id,
                    )
                )
            ).all()
        return [
            {
                "principal_id": str(principal_id),
                "principal_type": getattr(principal_type, "value", str(principal_type)),
            }
            for principal_id, principal_type in rows
        ]

    async def list_active_owners(self, tenant_id: UUID, app_id: UUID) -> list[UUID]:
        """Owners count only when their human membership is currently active."""
        async with self._sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(ApplicationOwnerModel.owner_principal_id)
                        .join(
                            MembershipModel,
                            and_(
                                MembershipModel.tenant_id == ApplicationOwnerModel.tenant_id,
                                MembershipModel.principal_id
                                == ApplicationOwnerModel.owner_principal_id,
                            ),
                        )
                        .join(
                            PrincipalModel,
                            and_(
                                PrincipalModel.tenant_id == MembershipModel.tenant_id,
                                PrincipalModel.id == MembershipModel.principal_id,
                            ),
                        )
                        .where(
                            ApplicationOwnerModel.tenant_id == tenant_id,
                            ApplicationOwnerModel.application_id == app_id,
                            MembershipModel.status == "active",
                            PrincipalModel.enabled.is_(True),
                            or_(
                                MembershipModel.expires_at.is_(None),
                                MembershipModel.expires_at > datetime.now().astimezone(),
                            ),
                        )
                    )
                ).all()
            )

    async def recompute_owner_state_for_principal(
        self, tenant_id: UUID, owner_principal_id: UUID
    ) -> int:
        """Atomically contain applications that lost their final active owner."""
        async with self._sessions.begin() as session:
            app_ids = list(
                (
                    await session.scalars(
                        select(ApplicationOwnerModel.application_id).where(
                            ApplicationOwnerModel.tenant_id == tenant_id,
                            ApplicationOwnerModel.owner_principal_id == owner_principal_id,
                        )
                    )
                ).all()
            )
            changed = 0
            for app_id in app_ids:
                active_owner = await session.scalar(
                    select(ApplicationOwnerModel.id)
                    .join(
                        MembershipModel,
                        and_(
                            MembershipModel.tenant_id == ApplicationOwnerModel.tenant_id,
                            MembershipModel.principal_id
                            == ApplicationOwnerModel.owner_principal_id,
                        ),
                    )
                    .join(
                        PrincipalModel,
                        and_(
                            PrincipalModel.tenant_id == MembershipModel.tenant_id,
                            PrincipalModel.id == MembershipModel.principal_id,
                        ),
                    )
                    .where(
                        ApplicationOwnerModel.tenant_id == tenant_id,
                        ApplicationOwnerModel.application_id == app_id,
                        MembershipModel.status == "active",
                        PrincipalModel.enabled.is_(True),
                        or_(
                            MembershipModel.expires_at.is_(None),
                            MembershipModel.expires_at > datetime.now().astimezone(),
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
                        changed += 1
                        session.add(
                            AuditEventModel(
                                tenant_id=tenant_id,
                                actor_principal_id=None,
                                action="application.ownerless_contained",
                                resource_type="application",
                                resource_id=str(app_id),
                                details={"reason_code": "no_active_owner"},
                            )
                        )
            return changed

    async def scan_ownerless_applications(self, tenant_id: UUID) -> int:
        """Idempotent governance scan for drift that missed a lifecycle event."""
        async with self._sessions() as session:
            app_ids = list(
                (
                    await session.scalars(
                        select(ApplicationModel.id).where(
                            ApplicationModel.tenant_id == tenant_id,
                            ApplicationModel.status == "active",
                        )
                    )
                ).all()
            )
            owner_ids = {
                app_id: list(
                    (
                        await session.scalars(
                            select(ApplicationOwnerModel.owner_principal_id).where(
                                ApplicationOwnerModel.tenant_id == tenant_id,
                                ApplicationOwnerModel.application_id == app_id,
                            )
                        )
                    ).all()
                )
                for app_id in app_ids
            }
        changed = 0
        for owners in owner_ids.values():
            for owner_id in owners:
                changed += await self.recompute_owner_state_for_principal(tenant_id, owner_id)
        # Applications with no owner rows need containment too.
        async with self._sessions.begin() as session:
            unowned_ids = list(
                (
                    await session.scalars(
                        select(ApplicationModel.id).where(
                            ApplicationModel.tenant_id == tenant_id,
                            ApplicationModel.status == "active",
                            ~ApplicationModel.id.in_(
                                [app_id for app_id, owners in owner_ids.items() if owners]
                            ),
                        )
                    )
                ).all()
            )
            if unowned_ids:
                result = await session.execute(
                    update(ApplicationModel)
                    .where(
                        ApplicationModel.tenant_id == tenant_id,
                        ApplicationModel.id.in_(unowned_ids),
                        ApplicationModel.status == "active",
                    )
                    .values(
                        status="pending_takeover",
                        authorization_version=ApplicationModel.authorization_version + 1,
                    )
                )
                changed += getattr(result, "rowcount", 0) or 0
                session.add_all(
                    [
                        AuditEventModel(
                            tenant_id=tenant_id,
                            actor_principal_id=None,
                            action="application.ownerless_contained",
                            resource_type="application",
                            resource_id=str(app_id),
                            details={"reason_code": "no_owner_record"},
                        )
                        for app_id in unowned_ids
                    ]
                )
        return changed

    async def list_keys(
        self, tenant_id: UUID, app_id: UUID, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, object]], str | None]:
        async with self._sessions() as session:
            statement = select(ApiKeyModel).where(
                ApiKeyModel.tenant_id == tenant_id, ApiKeyModel.application_id == app_id
            )
            if cursor:
                statement = statement.where(ApiKeyModel.id > UUID(cursor))
            models = (
                await session.scalars(statement.order_by(ApiKeyModel.id).limit(limit + 1))
            ).all()
        page, extra = models[:limit], len(models) > limit
        return [_api_key(item) for item in page], str(page[-1].id) if extra and page else None

    async def get_key(self, tenant_id: UUID, key_id: UUID) -> dict[str, object] | None:
        async with self._sessions() as session:
            model = await session.scalar(
                select(ApiKeyModel).where(
                    ApiKeyModel.tenant_id == tenant_id, ApiKeyModel.id == key_id
                )
            )
        return _api_key(model) if model else None

    async def create_key(
        self,
        tenant_id: UUID,
        app_id: UUID,
        key_id: str,
        digest: bytes,
        pepper_version: int,
        scopes: list[str],
        expires_at: datetime,
        *,
        actor_principal_id: UUID | None = None,
        audit_action: str = "api_key.issued",
    ) -> dict[str, object]:
        async with self._sessions.begin() as session:
            model = ApiKeyModel(
                tenant_id=tenant_id,
                application_id=app_id,
                key_id=key_id,
                secret_digest=digest,
                pepper_version=pepper_version,
                scopes=scopes,
                expires_at=expires_at,
                status="active",
            )
            session.add(model)
            await session.execute(
                update(ApplicationModel)
                .where(
                    ApplicationModel.tenant_id == tenant_id,
                    ApplicationModel.id == app_id,
                )
                .values(authorization_version=ApplicationModel.authorization_version + 1)
            )
            await session.flush()
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=actor_principal_id,
                    action=audit_action,
                    resource_type="api_key",
                    resource_id=str(model.id),
                    details={"application_id": str(app_id), "scope_count": len(scopes)},
                )
            )
            return _api_key(model)

    async def update_key(
        self,
        tenant_id: UUID,
        key_id: UUID,
        status: str,
        revoked_at: datetime | None,
        last_used_at: datetime | None,
        *,
        actor_principal_id: UUID | None = None,
        audit_action: str | None = None,
        reason_code: str | None = None,
    ) -> dict[str, object] | None:
        async with self._sessions.begin() as session:
            model = await session.scalar(
                select(ApiKeyModel)
                .where(ApiKeyModel.tenant_id == tenant_id, ApiKeyModel.id == key_id)
                .with_for_update()
            )
            if model is None:
                return None
            model.status, model.revoked_at, model.last_used_at = status, revoked_at, last_used_at
            await session.execute(
                update(ApplicationModel)
                .where(
                    ApplicationModel.tenant_id == tenant_id,
                    ApplicationModel.id == model.application_id,
                )
                .values(authorization_version=ApplicationModel.authorization_version + 1)
            )
            if audit_action:
                session.add(
                    AuditEventModel(
                        tenant_id=tenant_id,
                        actor_principal_id=actor_principal_id,
                        action=audit_action,
                        resource_type="api_key",
                        resource_id=str(model.id),
                        details={
                            "application_id": str(model.application_id),
                            "reason_code": reason_code or "not_provided",
                        },
                    )
                )
            await session.flush()
            return _api_key(model)

    async def record_security_audit(
        self,
        tenant_id: UUID,
        actor_principal_id: UUID,
        action: str,
        resource_type: str,
        resource_id: str | None,
        details: dict[str, object],
    ) -> None:
        async with self._sessions.begin() as session:
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

    async def get_key_state(self, tenant_id: UUID, key_id: UUID) -> dict[str, object] | None:
        """Read non-secret lifecycle state for delayed authorization checks."""
        async with self._sessions() as session:
            result = await session.execute(
                select(ApiKeyModel, ApplicationModel, PrincipalModel)
                .join(
                    ApplicationModel,
                    (ApplicationModel.tenant_id == ApiKeyModel.tenant_id)
                    & (ApplicationModel.id == ApiKeyModel.application_id),
                )
                .join(
                    PrincipalModel,
                    (PrincipalModel.tenant_id == ApplicationModel.tenant_id)
                    & (PrincipalModel.id == ApplicationModel.principal_id),
                )
                .where(ApiKeyModel.tenant_id == tenant_id, ApiKeyModel.id == key_id)
            )
            row = result.one_or_none()
        if row is None:
            return None
        key, application, principal = row
        return {
            "status": key.status,
            "expires_at": key.expires_at,
            "scopes": list(key.scopes),
            "application_id": str(application.id),
            "application_status": application.status,
            "application_authorization_version": application.authorization_version,
            "principal_id": str(principal.id),
            "principal_enabled": principal.enabled,
        }

    async def find_by_key_id(self, key_id: str) -> dict[str, object] | None:
        async with self._sessions() as session:
            row = await session.execute(
                select(ApiKeyModel, ApplicationModel, PrincipalModel)
                .join(
                    ApplicationModel,
                    (ApplicationModel.tenant_id == ApiKeyModel.tenant_id)
                    & (ApplicationModel.id == ApiKeyModel.application_id),
                )
                .join(
                    PrincipalModel,
                    (PrincipalModel.tenant_id == ApplicationModel.tenant_id)
                    & (PrincipalModel.id == ApplicationModel.principal_id),
                )
                .where(ApiKeyModel.key_id == key_id)
            )
            result = row.one_or_none()
        if result is None:
            return None
        key, application, principal = result
        record = _api_key(key)
        record.update(
            application_principal_id=str(principal.id),
            application_status=application.status,
            application_authorization_version=application.authorization_version,
            principal_enabled=principal.enabled,
            principal_type=principal.type.value,
        )
        return record
