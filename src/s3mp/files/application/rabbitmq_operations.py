"""Outbox publishing and RabbitMQ receiving for asynchronous file operations."""

import json
import logging
from typing import Any, Protocol
from uuid import UUID

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection
from redis.asyncio import Redis

from s3mp.common.rabbitmq import (
    EVENT_EXCHANGE,
    FILE_OPERATION_DLQ,
    FILE_OPERATION_QUEUE,
    FILE_OPERATION_ROUTING_KEY,
    RETRY_DELAYS,
    declare_file_operation_topology,
)
from s3mp.files.application.operation_worker import FileOperationWorker
from s3mp.files.infrastructure.operation_lock import FileOperationLockSet

logger = logging.getLogger(__name__)


class BrokerOperationStore(Protocol):
    async def claim_outbox_events(self, limit: int = 100) -> list[dict[str, Any]]: ...
    async def mark_outbox_published(self, event_id: UUID) -> None: ...
    async def release_outbox_event(self, event_id: UUID) -> None: ...
    async def start_broker_operation(
        self, tenant_id: UUID, operation_id: UUID
    ) -> dict[str, Any] | None: ...
    async def settle_broker_operation(
        self, tenant_id: UUID, operation_id: UUID, status: str, reason: str | None = None
    ) -> None: ...
    async def schedule_broker_retry(
        self, tenant_id: UUID, operation_id: UUID, reason: str | None = None
    ) -> dict[str, Any] | None: ...
    async def operation_file_ids(self, tenant_id: UUID, operation_id: UUID) -> list[UUID]: ...
    async def recover_timed_out_operations(
        self, timeout_seconds: int, max_recoveries: int, limit: int = 100
    ) -> int: ...
    async def record_dead_letter_event(
        self, tenant_id: UUID, operation_id: UUID | None, details: dict[str, Any]
    ) -> None: ...


class FileOperationOutboxPublisher:
    def __init__(self, store: BrokerOperationStore, connection: AbstractRobustConnection) -> None:
        self._store = store
        self._connection = connection

    async def publish_once(self, limit: int = 100) -> int:
        await declare_file_operation_topology(self._connection)
        channel = await self._connection.channel(publisher_confirms=True)
        exchange = await channel.get_exchange(EVENT_EXCHANGE)
        published = 0
        try:
            for event in await self._store.claim_outbox_events(limit):
                event_id = UUID(event["id"])
                payload = dict(event["payload"])
                payload["event_id"] = event["id"]
                try:
                    await exchange.publish(
                        aio_pika.Message(
                            json.dumps(payload, separators=(",", ":")).encode(),
                            content_type="application/json",
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            message_id=event["id"],
                            type=event["event_type"],
                        ),
                        routing_key=FILE_OPERATION_ROUTING_KEY,
                    )
                except Exception:
                    await self._store.release_outbox_event(event_id)
                    raise
                await self._store.mark_outbox_published(event_id)
                published += 1
        finally:
            await channel.close()
        return published


class RabbitMQFileOperationReceiver:
    def __init__(
        self,
        store: BrokerOperationStore,
        executor: FileOperationWorker,
        connection: AbstractRobustConnection,
        redis: Redis,
        *,
        max_retries: int,
        prefetch: int,
    ) -> None:
        self._store = store
        self._executor = executor
        self._connection = connection
        self._redis = redis
        self._max_retries = max_retries
        self._prefetch = prefetch

    async def consume(self) -> None:
        await declare_file_operation_topology(self._connection, prefetch=self._prefetch)
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=self._prefetch)
        queue = await channel.get_queue(FILE_OPERATION_QUEUE)
        await queue.consume(self._handle, no_ack=False)

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        try:
            event = json.loads(message.body)
            tenant_id = UUID(str(event["tenant_id"]))
            operation_id = UUID(str(event["operation_id"]))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            await message.reject(requeue=False)
            return
        operation = await self._store.start_broker_operation(tenant_id, operation_id)
        if operation is None:
            await message.ack()
            return
        lock = FileOperationLockSet(
            self._redis, await self._store.operation_file_ids(tenant_id, operation_id)
        )
        try:
            locked = await lock.acquire()
        except Exception:
            locked = False
        if not locked:
            await self._retry_or_dead_letter(message, operation, "redis_lock_unavailable")
            return
        try:
            status, reason = await self._executor.execute(operation)
        finally:
            await lock.release()
        if status == "retry_wait":
            await self._retry_or_dead_letter(
                message, operation, reason or "object_storage_unavailable"
            )
            return
        if status in {"partial_failure", "failed"}:
            await self._store.settle_broker_operation(
                tenant_id,
                operation_id,
                "partial_failure" if status == "partial_failure" else "dead_lettered",
                reason,
            )
            await message.reject(requeue=False)
            return
        await self._store.settle_broker_operation(tenant_id, operation_id, status, reason)
        await message.ack()

    async def _retry_or_dead_letter(
        self, message: AbstractIncomingMessage, operation: dict[str, Any], reason: str
    ) -> None:
        tenant_id, operation_id = UUID(operation["tenant_id"]), UUID(operation["id"])
        if int(operation.get("attempt_count", 0)) >= self._max_retries:
            await self._store.settle_broker_operation(
                tenant_id, operation_id, "dead_lettered", "retry_exhausted"
            )
            await message.reject(requeue=False)
            return
        retry = await self._store.schedule_broker_retry(tenant_id, operation_id, reason)
        if retry is None:
            await message.ack()
            return
        routing_key = _retry_routing_key(int(retry["attempt_count"]))
        channel = await self._connection.channel(publisher_confirms=True)
        try:
            exchange = await channel.get_exchange(EVENT_EXCHANGE)
            await exchange.publish(
                aio_pika.Message(
                    message.body,
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    message_id=message.message_id,
                ),
                routing_key=routing_key,
            )
        except Exception:
            await message.nack(requeue=True)
            return
        finally:
            await channel.close()
        await message.ack()


class RabbitMQDeadLetterReceiver:
    """Consumes DLQ messages for observable, safely-settled terminal events."""

    def __init__(
        self, store: BrokerOperationStore, connection: AbstractRobustConnection, *, prefetch: int
    ) -> None:
        self._store, self._connection, self._prefetch = store, connection, prefetch

    async def consume(self) -> None:
        await declare_file_operation_topology(self._connection, prefetch=self._prefetch)
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=self._prefetch)
        queue = await channel.get_queue(FILE_OPERATION_DLQ)
        await queue.consume(self._handle, no_ack=False)

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        try:
            event = json.loads(message.body)
            tenant_id = UUID(str(event["tenant_id"]))
            operation_id = UUID(str(event["operation_id"]))
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            await message.ack()
            return
        details = {
            "event_id": event.get("event_id"),
            "headers": dict(message.headers or {}),
            "routing_key": message.routing_key,
        }
        await self._store.record_dead_letter_event(tenant_id, operation_id, details)
        logger.error(
            "file_operation_dead_lettered",
            extra={"event": "file.operation.dead_lettered", **details},
        )
        await message.ack()


async def run_processing_recovery(
    store: BrokerOperationStore, *, timeout_seconds: int, max_recoveries: int, limit: int
) -> int:
    return await store.recover_timed_out_operations(timeout_seconds, max_recoveries, limit)


def _retry_routing_key(attempt_count: int) -> str:
    names = list(RETRY_DELAYS)
    return names[min(max(0, attempt_count - 1), len(names) - 1)]
