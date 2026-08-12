"""SQLAlchemy repository for file objects, uploads, multipart sessions, and operations."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.files.infrastructure.models import (
    FileObjectModel,
    FileOperationModel,
    MultipartPartModel,
    MultipartSessionModel,
    UploadSessionModel,
)


class SqlAlchemyFileStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    # ── Files ──────────────────────────────────────────────────────────────

    async def list_files(
        self, tenant_id: UUID, space_id: UUID, prefix: str
    ) -> list[dict[str, Any]]:
        async with self._sf() as session:
            stmt = select(FileObjectModel).where(
                FileObjectModel.tenant_id == tenant_id,
                FileObjectModel.storage_space_id == space_id,
            )
            if prefix:
                stmt = stmt.where(FileObjectModel.object_key.startswith(prefix))
            rows = (await session.scalars(stmt.order_by(FileObjectModel.object_key))).all()
            return [_file_dict(r) for r in rows]

    async def get_file(
        self, tenant_id: UUID, space_id: UUID, file_id: UUID
    ) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(FileObjectModel).where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.id == file_id,
                )
            )
            return _file_dict(row) if row else None

    async def delete_file(self, tenant_id: UUID, space_id: UUID, file_id: UUID, *, idempotency_key: str | None = None, if_match: str | None = None) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(FileObjectModel).where(
                    FileObjectModel.tenant_id == tenant_id,
                    FileObjectModel.storage_space_id == space_id,
                    FileObjectModel.id == file_id,
                )
            )
            if row is not None:
                await session.delete(row)

    async def create_operation(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            model = FileOperationModel(
                tenant_id=tenant_id,
                principal_id=UUID(data.get("principal_id", str(uuid4()))),
                operation_type=data["operation_type"],
                source_key=data.get("source_key"),
                destination_key=data.get("destination_key"),
                keys=data.get("keys", []),
                idempotency_key=data.get("idempotency_key", str(uuid4())),
                status="pending",
            )
            session.add(model)
            await session.flush()
            return _op_dict(model)

    async def get_operation(self, tenant_id: UUID, op_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(FileOperationModel).where(
                    FileOperationModel.tenant_id == tenant_id,
                    FileOperationModel.id == op_id,
                )
            )
            return _op_dict(row) if row else None

    # ── Uploads ────────────────────────────────────────────────────────────

    async def create_upload(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            model = UploadSessionModel(
                tenant_id=tenant_id,
                principal_id=UUID(data["principal_id"]),
                storage_space_id=space_id,
                object_key=data["object_key"],
                declared_length=data["content_length"],
                content_type=data["content_type"],
                checksum=data.get("checksum"),
                expires_at=datetime.now(UTC).replace(hour=23, minute=59, second=59),
                status="pending",
            )
            session.add(model)
            await session.flush()
            return _upload_dict(model)

    async def get_upload(self, tenant_id: UUID, upload_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(UploadSessionModel).where(
                    UploadSessionModel.tenant_id == tenant_id,
                    UploadSessionModel.id == upload_id,
                )
            )
            return _upload_dict(row) if row else None

    async def complete_upload(
        self, tenant_id: UUID, upload_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(UploadSessionModel).where(
                    UploadSessionModel.tenant_id == tenant_id,
                    UploadSessionModel.id == upload_id,
                ).with_for_update()
            )
            if row is None:
                raise ValueError("upload not found")
            row.status = "completed"
            row.completed_at = datetime.now(UTC)
            # Create file_object record so the file is visible in list_files
            file_obj = FileObjectModel(
                tenant_id=tenant_id,
                storage_space_id=row.storage_space_id,
                object_key=row.object_key,
                content_length=row.declared_length,
                content_type=row.content_type,
                checksum=data.get("checksum") or row.checksum,
                etag=data.get("etag"),
            )
            session.add(file_obj)
            await session.flush()
            result = _upload_dict(row)
            result["file_object"] = _file_dict(file_obj)
            return result

    # ── Multipart ──────────────────────────────────────────────────────────

    async def create_multipart(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            model = MultipartSessionModel(
                tenant_id=tenant_id,
                principal_id=UUID(data["principal_id"]),
                storage_space_id=space_id,
                object_key=data["object_key"],
                declared_length=data["content_length"],
                content_type=data["content_type"],
                quota_reservation_id=uuid4(),
                expires_at=datetime.now(UTC).replace(hour=23, minute=59, second=59),
                status="pending",
            )
            session.add(model)
            await session.flush()
            return _mp_dict(model)

    async def set_multipart_provider_id(
        self, tenant_id: UUID, multipart_id: UUID, provider_upload_id: str
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartSessionModel).where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == multipart_id,
                ).with_for_update()
            )
            if row is None:
                raise ValueError("multipart not found")
            row.provider_upload_id = provider_upload_id
            await session.flush()
            return _mp_dict(row)

    async def get_multipart(self, tenant_id: UUID, mp_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.scalar(
                select(MultipartSessionModel).where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == mp_id,
                )
            )
            return _mp_dict(row) if row else None

    async def abort_multipart(self, tenant_id: UUID, mp_id: UUID, *, idempotency_key: str | None = None) -> None:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartSessionModel).where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == mp_id,
                ).with_for_update()
            )
            if row is not None:
                row.status = "aborted"
                await session.flush()

    async def list_multipart_parts(self, tenant_id: UUID, mp_id: UUID) -> list[dict[str, Any]]:
        async with self._sf() as session:
            rows = await session.scalars(
                select(MultipartPartModel).where(
                    MultipartPartModel.tenant_id == tenant_id,
                    MultipartPartModel.multipart_session_id == mp_id,
                ).order_by(MultipartPartModel.part_number)
            )
            return [_part_dict(r) for r in rows]

    async def create_multipart_part(
        self, tenant_id: UUID, mp_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            model = MultipartPartModel(
                tenant_id=tenant_id,
                multipart_session_id=mp_id,
                part_number=data["part_number"],
                etag="pending",
                content_length=0,
            )
            session.add(model)
            await session.flush()
            return _part_dict(model)

    async def confirm_multipart_part(
        self, tenant_id: UUID, mp_id: UUID, part_number: int, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartPartModel).where(
                    MultipartPartModel.tenant_id == tenant_id,
                    MultipartPartModel.multipart_session_id == mp_id,
                    MultipartPartModel.part_number == part_number,
                ).with_for_update()
            )
            if row is None:
                raise ValueError("part not found")
            row.etag = data["etag"]
            row.content_length = data["content_length"]
            await session.flush()
            return _part_dict(row)

    async def complete_multipart(
        self, tenant_id: UUID, mp_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._sf.begin() as session:
            row = await session.scalar(
                select(MultipartSessionModel).where(
                    MultipartSessionModel.tenant_id == tenant_id,
                    MultipartSessionModel.id == mp_id,
                ).with_for_update()
            )
            if row is None:
                raise ValueError("multipart not found")
            row.status = "completed"
            await session.flush()
            return _mp_dict(row)


def _file_dict(m: FileObjectModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "storage_space_id": str(m.storage_space_id), "object_key": m.object_key,
        "content_length": m.content_length, "content_type": m.content_type,
        "etag": m.etag, "checksum": m.checksum,
        "created_at": m.created_at.isoformat(),
    }


def _upload_dict(m: UploadSessionModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "principal_id": str(m.principal_id), "object_key": m.object_key,
        "content_length": m.declared_length, "content_type": m.content_type,
        "status": m.status, "checksum": m.checksum,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
    }


def _mp_dict(m: MultipartSessionModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "principal_id": str(m.principal_id), "object_key": m.object_key,
        "content_length": m.declared_length, "content_type": m.content_type,
        "status": m.status, "provider_upload_id": m.provider_upload_id,
        "expires_at": m.expires_at.isoformat() if m.expires_at else None,
    }


def _part_dict(m: MultipartPartModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "part_number": m.part_number,
        "etag": m.etag, "content_length": m.content_length,
    }


def _op_dict(m: FileOperationModel) -> dict[str, Any]:
    return {
        "id": str(m.id), "tenant_id": str(m.tenant_id),
        "operation_type": m.operation_type, "status": m.status,
        "source_key": m.source_key, "destination_key": m.destination_key,
        "failure_reason": m.failure_reason,
        "created_at": m.created_at.isoformat(),
    }
