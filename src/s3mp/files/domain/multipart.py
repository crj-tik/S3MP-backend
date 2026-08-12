"""Tenant-bound multipart and object-mutation state machines."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from s3mp.files.domain.service import FileValidationError, ObjectMetadata
from s3mp.storage.domain.policy import canonical_object_key


class MultipartStatus(StrEnum):
    PENDING = "pending"
    COMPLETING = "completing"
    COMPLETED = "completed"
    ABORTED = "aborted"
    EXPIRED = "expired"
    FAILED = "failed"


class OperationStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MultipartPart:
    number: int
    etag: str
    size: int


@dataclass(frozen=True, slots=True)
class MultipartSession:
    id: UUID
    tenant_id: UUID
    principal_id: UUID
    storage_space_id: UUID
    object_key: str
    declared_length: int
    content_type: str
    quota_reservation_id: UUID
    expires_at: datetime
    status: MultipartStatus = MultipartStatus.PENDING
    provider_upload_id: str | None = None
    parts: tuple[MultipartPart, ...] = ()


@dataclass(frozen=True, slots=True)
class ObjectOperation:
    id: UUID
    tenant_id: UUID
    principal_id: UUID
    kind: str
    source_key: str | None
    destination_key: str | None
    status: OperationStatus = OperationStatus.PENDING
    failure_reason: str | None = None


class MultipartStore(Protocol):
    async def create_multipart(self, key: str, content_type: str) -> str: ...

    async def upload_part(self, upload_id: str, number: int, body: bytes) -> MultipartPart: ...

    async def list_parts(self, upload_id: str) -> list[MultipartPart]: ...

    async def complete_multipart(
        self, upload_id: str, parts: list[MultipartPart]
    ) -> ObjectMetadata: ...

    async def abort_multipart(self, upload_id: str) -> None: ...

    async def copy(self, source_key: str, destination_key: str) -> ObjectMetadata: ...

    async def delete(self, key: str) -> None: ...


class MultipartService:
    def __init__(self, store: MultipartStore) -> None:
        self._store = store

    async def create(self, session: MultipartSession) -> MultipartSession:
        self._pending(session)
        canonical_object_key(session.object_key)
        upload_id = await self._store.create_multipart(session.object_key, session.content_type)
        return replace(session, provider_upload_id=upload_id)

    async def add_part(
        self, session: MultipartSession, principal_id: UUID, number: int, body: bytes
    ) -> MultipartSession:
        self._owned(session, principal_id)
        self._pending(session)
        if not session.provider_upload_id or number < 1 or not body:
            raise FileValidationError("invalid multipart part")
        part = await self._store.upload_part(session.provider_upload_id, number, body)
        parts = {existing.number: existing for existing in session.parts}
        parts[number] = part
        return replace(session, parts=tuple(parts[key] for key in sorted(parts)))

    async def list_parts(
        self, session: MultipartSession, principal_id: UUID
    ) -> list[MultipartPart]:
        self._owned(session, principal_id)
        self._pending(session)
        if not session.provider_upload_id:
            raise FileValidationError("multipart upload has not been created")
        return await self._store.list_parts(session.provider_upload_id)

    async def complete(
        self, session: MultipartSession, principal_id: UUID
    ) -> tuple[MultipartSession, ObjectMetadata]:
        self._owned(session, principal_id)
        self._pending(session)
        if not session.provider_upload_id or not session.parts:
            raise FileValidationError("multipart upload has no confirmed parts")
        expected = list(range(1, len(session.parts) + 1))
        if [part.number for part in session.parts] != expected:
            raise FileValidationError("multipart part numbers must be contiguous")
        if sum(part.size for part in session.parts) != session.declared_length:
            raise FileValidationError("multipart size does not match declared length")
        metadata = await self._store.complete_multipart(
            session.provider_upload_id, list(session.parts)
        )
        if metadata.key != session.object_key or metadata.content_length != session.declared_length:
            raise FileValidationError("completed multipart object does not match session")
        return replace(session, status=MultipartStatus.COMPLETED), metadata

    async def abort(self, session: MultipartSession, principal_id: UUID) -> MultipartSession:
        self._owned(session, principal_id)
        if session.status is MultipartStatus.ABORTED:
            return session
        if session.status is not MultipartStatus.PENDING:
            raise FileValidationError("multipart session cannot be aborted")
        if session.provider_upload_id:
            await self._store.abort_multipart(session.provider_upload_id)
        return replace(session, status=MultipartStatus.ABORTED)

    async def cleanup_expired(
        self, sessions: list[MultipartSession], now: datetime
    ) -> list[MultipartSession]:
        cleaned: list[MultipartSession] = []
        for session in sessions:
            if session.status is MultipartStatus.PENDING and session.expires_at <= now:
                if session.provider_upload_id:
                    await self._store.abort_multipart(session.provider_upload_id)
                cleaned.append(replace(session, status=MultipartStatus.EXPIRED))
        return cleaned

    async def move(self, operation: ObjectOperation) -> ObjectOperation:
        if operation.kind != "move" or not operation.source_key or not operation.destination_key:
            raise FileValidationError("invalid move operation")
        canonical_object_key(operation.source_key)
        canonical_object_key(operation.destination_key)
        try:
            copied = await self._store.copy(operation.source_key, operation.destination_key)
        except Exception as error:
            return replace(operation, status=OperationStatus.FAILED, failure_reason=str(error))
        if copied.key != operation.destination_key:
            return replace(
                operation, status=OperationStatus.FAILED, failure_reason="copy verification failed"
            )
        try:
            await self._store.delete(operation.source_key)
        except Exception as error:
            return replace(
                operation,
                status=OperationStatus.PARTIAL_FAILURE,
                failure_reason=f"source delete failed: {error}",
            )
        return replace(operation, status=OperationStatus.COMPLETED)

    async def delete_batch(
        self,
        keys: list[str],
        confirmed_keys: list[str],
        operation_id: UUID,
        *,
        tenant_id: UUID,
        principal_id: UUID,
    ) -> ObjectOperation:
        if not keys or sorted(set(keys)) != sorted(set(confirmed_keys)):
            raise FileValidationError("batch delete confirmation does not match requested scope")
        for key in keys:
            canonical_object_key(key)
        operation = ObjectOperation(
            operation_id, tenant_id, principal_id, "batch_delete", None, None
        )
        try:
            for key in sorted(set(keys)):
                await self._store.delete(key)
        except Exception as error:
            return replace(
                operation, status=OperationStatus.PARTIAL_FAILURE, failure_reason=str(error)
            )
        return replace(operation, status=OperationStatus.COMPLETED)

    @staticmethod
    def _owned(session: MultipartSession, principal_id: UUID) -> None:
        if session.principal_id != principal_id:
            raise FileValidationError("multipart session belongs to a different principal")

    @staticmethod
    def _pending(session: MultipartSession) -> None:
        if session.status is not MultipartStatus.PENDING or session.expires_at <= datetime.now(UTC):
            raise FileValidationError("multipart session is not pending")
