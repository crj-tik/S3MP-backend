"""SQLAlchemy storage connection and space repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.applications.infrastructure.models import ApplicationModel
from s3mp.storage.infrastructure.models import (
    PlatformStorageProfileModel,
    StorageConnectionModel,
    StorageSpaceModel,
)
from s3mp.tenant.infrastructure.models import TenantModel


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
        "application_id": str(model.application_id) if model.application_id else None,
        "name": model.name,
        "bucket": model.bucket,
        "root_prefix": model.root_prefix,
        "storage_namespace": model.storage_namespace,
        "profile_version": model.profile_version,
        "provider_target_version": model.provider_target_version,
        "status": model.status,
        "created_at": model.created_at,
    }


def _profile(model: PlatformStorageProfileModel) -> dict[str, object]:
    return {
        "id": str(model.id),
        "name": model.name,
        "endpoint": model.endpoint,
        "region": model.region,
        "bucket": model.bucket,
        "path_style": model.path_style,
        "signature_version": model.signature_version,
        "credential_reference": model.credential_reference,
        "profile_version": model.profile_version,
        "status": model.status,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }


class SqlAlchemyStorageStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def get_active_platform_profile(self) -> dict[str, object] | None:
        async with self._sessions() as session:
            model = await session.scalar(
                select(PlatformStorageProfileModel)
                .where(PlatformStorageProfileModel.status == "active")
                .order_by(PlatformStorageProfileModel.profile_version.desc())
            )
        return _profile(model) if model else None

    async def ensure_platform_profile(
        self,
        *,
        endpoint: str,
        region: str,
        bucket: str,
        path_style: bool,
        credential_reference: str = "settings:s3",
    ) -> dict[str, object]:
        """Materialize the validated deployment S3 target as the active profile."""
        async with self._sessions.begin() as session:
            model = await session.scalar(
                select(PlatformStorageProfileModel)
                .where(PlatformStorageProfileModel.status == "active")
                .order_by(PlatformStorageProfileModel.profile_version.desc())
                .with_for_update()
            )
            if model is None:
                model = PlatformStorageProfileModel(
                    name="default-shared-s3",
                    endpoint=endpoint,
                    region=region,
                    bucket=bucket,
                    path_style=path_style,
                    credential_reference=credential_reference,
                    profile_version=1,
                    status="active",
                )
                session.add(model)
                await session.flush()
            elif (
                model.endpoint != endpoint
                or model.region != region
                or model.bucket != bucket
                or model.path_style != path_style
            ):
                model.endpoint = endpoint
                model.region = region
                model.bucket = bucket
                model.path_style = path_style
                model.profile_version += 1
                model.credential_reference = credential_reference
                await session.flush()
            await session.refresh(model)
            return _profile(model)

    async def list_connections(
        self, tenant_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, object]], str | None]:
        async with self._sessions() as session:
            statement = (
                select(StorageConnectionModel)
                .join(TenantModel, TenantModel.id == StorageConnectionModel.tenant_id)
                .where(
                    StorageConnectionModel.tenant_id == tenant_id,
                    StorageConnectionModel.status == "active",
                    TenantModel.status == "active",
                )
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
                    StorageConnectionModel.status == "active",
                    StorageConnectionModel.tenant_id.in_(
                        select(TenantModel.id).where(TenantModel.status == "active")
                    ),
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

    async def ensure_managed_connection(
        self, tenant_id: UUID, profile: dict[str, object]
    ) -> dict[str, object]:
        """Return the server-owned compatibility connection for one tenant.

        ``storage_space.connection_id`` is retained for relational integrity
        during the cutover.  It must never be chosen by a tenant request or
        used as the provider target; the active platform profile remains the
        sole source of endpoint, bucket and credentials.
        """
        profile_version = profile["profile_version"]
        if not isinstance(profile_version, int) or profile_version < 1:
            raise ValueError("active profile has an invalid version")
        version = profile_version
        name = f"__s3mp_managed_shared_profile_v{version}__"
        async with self._sessions.begin() as session:
            model = await session.scalar(
                select(StorageConnectionModel)
                .where(
                    StorageConnectionModel.tenant_id == tenant_id,
                    StorageConnectionModel.name == name,
                )
                .with_for_update()
            )
            if model is None:
                model = StorageConnectionModel(
                    tenant_id=tenant_id,
                    name=name,
                    endpoint=str(profile["endpoint"]),
                    region=str(profile["region"]),
                    path_style=bool(profile["path_style"]),
                    credential_reference=str(profile.get("credential_reference", "settings:s3")),
                    capabilities={
                        "list_objects": True,
                        "head_object": True,
                        "proxy_upload": True,
                        "presigned_get": True,
                        "presigned_put": True,
                        "multipart": True,
                        "copy_object": True,
                        "delete_object": True,
                    },
                    status="active",
                )
                session.add(model)
                await session.flush()
            elif (
                model.endpoint != str(profile["endpoint"])
                or model.region != str(profile["region"])
                or model.path_style != bool(profile["path_style"])
                or model.status != "active"
            ):
                raise ValueError("managed connection does not match active profile")
            return _connection(model)

    async def list_spaces(
        self, tenant_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, object]], str | None]:
        async with self._sessions() as session:
            statement = (
                select(StorageSpaceModel)
                .join(TenantModel, TenantModel.id == StorageSpaceModel.tenant_id)
                .join(
                    StorageConnectionModel,
                    (StorageConnectionModel.tenant_id == StorageSpaceModel.tenant_id)
                    & (StorageConnectionModel.id == StorageSpaceModel.connection_id),
                )
                .join(
                    ApplicationModel,
                    (ApplicationModel.tenant_id == StorageSpaceModel.tenant_id)
                    & (ApplicationModel.id == StorageSpaceModel.application_id),
                )
                .where(
                    StorageSpaceModel.tenant_id == tenant_id,
                    StorageSpaceModel.status == "active",
                    StorageConnectionModel.status == "active",
                    ApplicationModel.status == "active",
                    StorageSpaceModel.storage_namespace.is_not(None),
                    TenantModel.status == "active",
                )
            )
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
                    StorageSpaceModel.tenant_id == tenant_id,
                    StorageSpaceModel.id == space_id,
                    StorageSpaceModel.status == "active",
                    StorageSpaceModel.tenant_id.in_(
                        select(TenantModel.id).where(TenantModel.status == "active")
                    ),
                    StorageSpaceModel.application_id.is_not(None),
                    StorageSpaceModel.storage_namespace.is_not(None),
                    StorageSpaceModel.application_id.in_(
                        select(ApplicationModel.id).where(
                            ApplicationModel.tenant_id == tenant_id,
                            ApplicationModel.status == "active",
                        )
                    ),
                    StorageSpaceModel.connection_id.in_(
                        select(StorageConnectionModel.id).where(
                            StorageConnectionModel.tenant_id == tenant_id,
                            StorageConnectionModel.status == "active",
                        )
                    ),
                )
            )
        return _space(model) if model else None

    async def create_space(self, tenant_id: UUID, data: dict[str, object]) -> dict[str, object]:
        async with self._sessions.begin() as session:
            application_id = data.get("application_id")
            if application_id is not None:
                application = await session.scalar(
                    select(ApplicationModel).where(
                        ApplicationModel.tenant_id == tenant_id,
                        ApplicationModel.id == UUID(str(application_id)),
                        ApplicationModel.status == "active",
                    )
                )
                if application is None:
                    raise ValueError("application is not active in this tenant")
                data = {
                    **data,
                    "storage_namespace": application.storage_namespace,
                }
            model = StorageSpaceModel(tenant_id=tenant_id, **data)
            session.add(model)
            await session.flush()
            return _space(model)
