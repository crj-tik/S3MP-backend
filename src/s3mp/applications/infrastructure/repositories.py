"""Tenant-scoped SQLAlchemy repositories for application lifecycle services."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.applications.infrastructure.models import (
    ApiKeyModel,
    ApplicationModel,
    ApplicationOwnerModel,
)


def _application(model: ApplicationModel) -> dict[str, object]:
    return {
        "id": str(model.id),
        "tenant_id": model.tenant_id,
        "principal_id": model.principal_id,
        "name": model.name,
        "status": model.status,
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
            model = ApplicationModel(
                tenant_id=tenant_id, name=name, principal_id=principal_id, status="active"
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
            await session.flush()
            return _api_key(model)

    async def update_key(
        self,
        tenant_id: UUID,
        key_id: UUID,
        status: str,
        revoked_at: datetime | None,
        last_used_at: datetime | None,
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
            await session.flush()
            return _api_key(model)

    async def find_by_key_id(self, key_id: str) -> dict[str, object] | None:
        async with self._sessions() as session:
            model = await session.scalar(select(ApiKeyModel).where(ApiKeyModel.key_id == key_id))
        return _api_key(model) if model else None
