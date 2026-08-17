"""SQLAlchemy storage connection and space repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.storage.infrastructure.models import StorageConnectionModel, StorageSpaceModel


def _connection(model: StorageConnectionModel) -> dict[str, object]:
    return {
        "id": str(model.id),
        "tenant_id": model.tenant_id,
        "name": model.name,
        "endpoint": model.endpoint,
        "region": model.region,
        "path_style": model.path_style,
        "credential_reference": model.credential_reference,
        "capabilities": dict(model.capabilities),
        "status": model.status,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }


def _space(model: StorageSpaceModel) -> dict[str, object]:
    return {
        "id": str(model.id),
        "tenant_id": model.tenant_id,
        "connection_id": str(model.connection_id),
        "name": model.name,
        "bucket": model.bucket,
        "root_prefix": model.root_prefix,
        "provider_target_version": model.provider_target_version,
        "status": model.status,
        "created_at": model.created_at,
    }


class SqlAlchemyStorageStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def list_connections(
        self, tenant_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, object]], str | None]:
        async with self._sessions() as session:
            statement = select(StorageConnectionModel).where(
                StorageConnectionModel.tenant_id == tenant_id
            )
            if cursor:
                statement = statement.where(StorageConnectionModel.id > UUID(cursor))
            models = (
                await session.scalars(
                    statement.order_by(StorageConnectionModel.id).limit(limit + 1)
                )
            ).all()
        page, extra = models[:limit], len(models) > limit
        return [_connection(item) for item in page], str(page[-1].id) if extra and page else None

    async def get_connection(self, tenant_id: UUID, conn_id: UUID) -> dict[str, object] | None:
        async with self._sessions() as session:
            model = await session.scalar(
                select(StorageConnectionModel).where(
                    StorageConnectionModel.tenant_id == tenant_id,
                    StorageConnectionModel.id == conn_id,
                )
            )
        return _connection(model) if model else None

    async def create_connection(
        self, tenant_id: UUID, data: dict[str, object]
    ) -> dict[str, object]:
        async with self._sessions.begin() as session:
            model = StorageConnectionModel(tenant_id=tenant_id, **data)
            session.add(model)
            await session.flush()
            return _connection(model)

    async def list_spaces(
        self, tenant_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, object]], str | None]:
        async with self._sessions() as session:
            statement = select(StorageSpaceModel).where(StorageSpaceModel.tenant_id == tenant_id)
            if cursor:
                statement = statement.where(StorageSpaceModel.id > UUID(cursor))
            models = (
                await session.scalars(statement.order_by(StorageSpaceModel.id).limit(limit + 1))
            ).all()
        page, extra = models[:limit], len(models) > limit
        return [_space(item) for item in page], str(page[-1].id) if extra and page else None

    async def get_space(self, tenant_id: UUID, space_id: UUID) -> dict[str, object] | None:
        async with self._sessions() as session:
            model = await session.scalar(
                select(StorageSpaceModel).where(
                    StorageSpaceModel.tenant_id == tenant_id, StorageSpaceModel.id == space_id
                )
            )
        return _space(model) if model else None

    async def create_space(self, tenant_id: UUID, data: dict[str, object]) -> dict[str, object]:
        async with self._sessions.begin() as session:
            model = StorageSpaceModel(tenant_id=tenant_id, **data)
            session.add(model)
            await session.flush()
            return _space(model)
