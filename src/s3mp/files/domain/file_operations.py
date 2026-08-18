"""Domain values for durable object mutation operations.

Upload sessions and provider multipart state are owned by the application
service and persistence layer.  This module only keeps the enum catalog and
the independent move/delete operation state machine.
"""

from dataclasses import dataclass, replace
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
class ObjectOperation:
    id: UUID
    tenant_id: UUID
    principal_id: UUID
    kind: str
    source_key: str | None
    destination_key: str | None
    status: OperationStatus = OperationStatus.PENDING
    failure_reason: str | None = None


class ObjectMutationStore(Protocol):
    async def copy(self, source_key: str, destination_key: str) -> ObjectMetadata: ...

    async def delete(self, key: str) -> None: ...


class ObjectMutationService:
    def __init__(self, store: ObjectMutationStore) -> None:
        self._store = store

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
