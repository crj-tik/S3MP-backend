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
        "status": model.status,
        "created_at": model.created_at,
    }


class SqlAlchemyStorageStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def list_connections(self, tenant_id: UUID) -> list[dict[str, object]]:
        async with self._sessions() as session:
            models = (
                await session.scalars(
                    select(StorageConnectionModel)
                    .where(StorageConnectionModel.tenant_id == tenant_id)
                    .order_by(StorageConnectionModel.name)
                )
            ).all()
        return [_connection(item) for item in models]

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

    async def list_spaces(self, tenant_id: UUID) -> list[dict[str, object]]:
        async with self._sessions() as session:
            models = (
                await session.scalars(
                    select(StorageSpaceModel)
                    .where(StorageSpaceModel.tenant_id == tenant_id)
                    .order_by(StorageSpaceModel.name)
                )
            ).all()
        return [_space(item) for item in models]

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
