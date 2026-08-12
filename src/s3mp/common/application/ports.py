"""Typed ports for application services: repositories, authorization, idempotency, quota, audit, object storage, clock, and outbox."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

# ── Shared results ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PageResult:
    items: list[dict[str, Any]]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class MutationResult:
    record: dict[str, Any]
    etag: str


# ── Clock ─────────────────────────────────────────────────────────────────────


@runtime_checkable
class Clock(Protocol):
    @abstractmethod
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        from datetime import UTC, datetime
        return datetime.now(UTC)


# ── Idempotency ───────────────────────────────────────────────────────────────


@runtime_checkable
class IdempotencyStore(Protocol):
    @abstractmethod
    async def get(self, fingerprint: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def put(self, fingerprint: str, result: dict[str, Any]) -> None: ...


# ── Audit ─────────────────────────────────────────────────────────────────────


@runtime_checkable
class AuditPort(Protocol):
    @abstractmethod
    async def record(
        self,
        tenant_id: UUID,
        action: str,
        resource_type: str,
        *,
        actor_principal_id: UUID | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None: ...

    @abstractmethod
    async def record_verified(
        self,
        tenant_id: UUID,
        action: str,
        resource_type: str,
        *,
        actor_principal_id: UUID | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool: ...


# ── Quota ─────────────────────────────────────────────────────────────────────


@runtime_checkable
class QuotaPort(Protocol):
    @abstractmethod
    async def reserve(
        self, tenant_id: UUID, space_id: UUID, bytes_requested: int
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def settle(
        self, tenant_id: UUID, reservation_id: UUID, actual_bytes: int
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def release(self, tenant_id: UUID, reservation_id: UUID) -> None: ...


# ── Object Storage ────────────────────────────────────────────────────────────


@runtime_checkable
class ObjectStoragePort(Protocol):
    @abstractmethod
    async def put_object(
        self, bucket: str, key: str, body: bytes, content_type: str
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def get_object(self, bucket: str, key: str) -> bytes: ...

    @abstractmethod
    async def head_object(self, bucket: str, key: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def delete_object(self, bucket: str, key: str) -> None: ...

    @abstractmethod
    async def list_objects(self, bucket: str, prefix: str) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def create_multipart(self, bucket: str, key: str, content_type: str) -> str: ...

    @abstractmethod
    async def complete_multipart(
        self, bucket: str, key: str, upload_id: str, parts: list[dict[str, Any]]
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def abort_multipart(self, bucket: str, key: str, upload_id: str) -> None: ...

    @abstractmethod
    async def copy_object(
        self, source_bucket: str, source_key: str, dest_bucket: str, dest_key: str
    ) -> dict[str, Any]: ...

    @abstractmethod
    async def presign_get(
        self, bucket: str, key: str, ttl_seconds: int
    ) -> str: ...

    @abstractmethod
    async def presign_put(
        self, bucket: str, key: str, ttl_seconds: int
    ) -> str: ...

    @abstractmethod
    async def probe(self) -> dict[str, Any]: ...


# ── Outbox / Worker ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: UUID
    tenant_id: UUID
    topic: str
    payload: dict[str, Any]
    created_at: datetime


@runtime_checkable
class OutboxPort(Protocol):
    @abstractmethod
    async def enqueue(self, message: OutboxMessage) -> None: ...

    @abstractmethod
    async def dequeue(self, topic: str, batch_size: int = 10) -> list[OutboxMessage]: ...

    @abstractmethod
    async def ack(self, message_id: UUID) -> None: ...

    @abstractmethod
    async def nack(self, message_id: UUID, reason: str) -> None: ...


# ── Service context ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ServiceContext:
    """Typed boundary passed to every application service."""
    tenant_id: UUID
    principal_id: UUID
    membership_id: UUID
    authorization_version: int