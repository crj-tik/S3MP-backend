"""Durable publishing and consuming for analysis tasks."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol
from uuid import UUID

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection

from s3mp.common.rabbitmq import (
    EVENT_EXCHANGE,
    KNOWLEDGE_ANALYSIS_QUEUE,
    KNOWLEDGE_ANALYSIS_ROUTING_KEY,
    KNOWLEDGE_INDEX_QUEUE,
    KNOWLEDGE_INDEX_ROUTING_KEY,
    KNOWLEDGE_RETRY_DELAYS,
    declare_knowledge_topology,
)

logger = logging.getLogger(__name__)


class KnowledgeBrokerStore(Protocol):
    async def claim_outbox_events(self, limit: int = 100) -> list[dict[str, Any]]: ...
    async def mark_outbox_published(self, event_id: UUID) -> None: ...
    async def release_outbox_event(self, event_id: UUID) -> None: ...
    async def claim_task(self, tenant_id: UUID, task_id: UUID) -> dict[str, Any] | None: ...
    async def schedule_retry(
        self, tenant_id: UUID, task_id: UUID, reason: str, max_retries: int
    ) -> dict[str, Any] | None: ...
    async def settle_task(
        self, tenant_id: UUID, task_id: UUID, state: str, reason: str | None = None
    ) -> None: ...
    async def record_dead_letter(
        self, tenant_id: UUID, task_id: UUID | None, details: dict[str, object]
    ) -> None: ...


class KnowledgeOutboxPublisher:
    def __init__(self, store: KnowledgeBrokerStore, connection: AbstractRobustConnection) -> None:
        self._store, self._connection = store, connection

    async def publish_once(self, limit: int = 100) -> int:
        await declare_knowledge_topology(self._connection)
        channel = await self._connection.channel(publisher_confirms=True)
        exchange = await channel.get_exchange(EVENT_EXCHANGE)
        count = 0
        try:
            for event in await self._store.claim_outbox_events(limit):
                try:
                    await exchange.publish(
                        aio_pika.Message(
                            json.dumps(event["payload"], separators=(",", ":")).encode(),
                            content_type="application/json",
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            message_id=event["id"],
                            type=event["event_type"],
                        ),
                        routing_key=_routing_key(event["event_type"]),
                    )
                except Exception:
                    await self._store.release_outbox_event(UUID(event["id"]))
                    raise
                await self._store.mark_outbox_published(UUID(event["id"]))
                count += 1
        finally:
            await channel.close()
        return count


class KnowledgeAnalysisReceiver:
    """Claims tasks once; failures are delayed through the isolated retry queues."""

    def __init__(
        self,
        store: KnowledgeBrokerStore,
        connection: AbstractRobustConnection,
        executor: KnowledgeTaskExecutor,
        *,
        max_retries: int,
        prefetch: int,
    ) -> None:
        self._store, self._connection, self._executor = store, connection, executor
        self._max_retries, self._prefetch = max_retries, prefetch

    async def consume(self) -> None:
        await declare_knowledge_topology(self._connection, prefetch=self._prefetch)
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=self._prefetch)
        await (await channel.get_queue(KNOWLEDGE_ANALYSIS_QUEUE)).consume(
            self._handle, no_ack=False
        )

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        try:
            payload = json.loads(message.body)
            tenant_id, task_id = UUID(payload["tenant_id"]), UUID(payload["task_id"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            await message.reject(requeue=False)
            return
        task = await self._store.claim_task(tenant_id, task_id)
        if task is None:
            await message.ack()
            return
        try:
            status, reason = await self._executor.execute(task)
        except Exception:
            logger.exception("knowledge_analysis_execution_failed", extra={"task_id": str(task_id)})
            status, reason = "retry", "unhandled_worker_error"
        if status == "completed" or status == "skipped":
            await self._store.settle_task(tenant_id, task_id, status, reason)
            await message.ack()
            return
        await self._retry_or_dead_letter(message, task, reason or "processing_failed")

    async def _retry_or_dead_letter(
        self, message: AbstractIncomingMessage, task: dict[str, Any], reason: str
    ) -> None:
        tenant_id, task_id = UUID(task["tenant_id"]), UUID(task["id"])
        result = await self._store.schedule_retry(tenant_id, task_id, reason, self._max_retries)
        if result is None:
            await message.ack()
            return
        if result["state"] == "dead_lettered":
            await self._store.record_dead_letter(tenant_id, task_id, {"reason": reason})
            await message.reject(requeue=False)
            return
        attempt = int(result["attempt_count"])
        delay_name = list(KNOWLEDGE_RETRY_DELAYS)[min(attempt - 1, 2)]
        retry_suffix = delay_name.rsplit(".", 1)[-1]
        retry_key = f"{KNOWLEDGE_ANALYSIS_ROUTING_KEY}.{retry_suffix}"
        channel = await self._connection.channel(publisher_confirms=True)
        try:
            await (await channel.get_exchange(EVENT_EXCHANGE)).publish(
                aio_pika.Message(
                    message.body,
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    message_id=message.message_id,
                ),
                routing_key=retry_key,
            )
        except Exception:
            await message.nack(requeue=True)
            return
        finally:
            await channel.close()
        await message.ack()


class KnowledgeTaskExecutor(Protocol):
    async def execute(self, task: dict[str, Any]) -> tuple[str, str | None]: ...


class KnowledgeIndexReceiver:
    """Projection-only receiver; retries never publish analysis events."""

    def __init__(
        self,
        connection: AbstractRobustConnection,
        executor: IndexExecutor,
        store: IndexProjectionStore,
        *,
        prefetch: int,
    ) -> None:
        self._connection, self._executor, self._store, self._prefetch = (
            connection,
            executor,
            store,
            prefetch,
        )

    async def consume(self) -> None:
        await declare_knowledge_topology(self._connection, prefetch=self._prefetch)
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=self._prefetch)
        await (await channel.get_queue(KNOWLEDGE_INDEX_QUEUE)).consume(self._handle, no_ack=False)

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        event: dict[str, Any] | None = None
        try:
            event = json.loads(message.body)
            if not isinstance(event, dict):
                raise ValueError("index event must be an object")
            status, reason = await self._executor.execute(event)
        except Exception:
            logger.exception("knowledge_index_projection_failed")
            status, reason = "retry", "projection_exception"
        # A malformed message cannot name a card whose state can be updated.
        # Reject it immediately instead of repeatedly retrying an untraceable event.
        if event is None:
            await message.reject(requeue=False)
            return
        if status == "completed":
            await self._set_projection_state(event, "indexed")
            await message.ack()
            return
        raw_retries = (message.headers or {}).get("x-knowledge-retries", 0)
        retries = int(raw_retries) if isinstance(raw_retries, (int, str)) else 0
        if retries >= 3:
            await self._set_projection_state(event, "dead_lettered")
            await message.reject(requeue=False)
            return
        await self._set_projection_state(event, "retrying")
        channel = await self._connection.channel(publisher_confirms=True)
        try:
            retry_suffix = list(KNOWLEDGE_RETRY_DELAYS)[min(retries, 2)].rsplit(".", 1)[-1]
            await (await channel.get_exchange(EVENT_EXCHANGE)).publish(
                aio_pika.Message(
                    message.body,
                    headers={
                        "x-knowledge-retries": retries + 1,
                        "x-failure-reason": reason or "unknown",
                    },
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=f"{KNOWLEDGE_INDEX_ROUTING_KEY}.{retry_suffix}",
            )
        finally:
            await channel.close()
        await message.ack()

    async def _set_projection_state(self, event: dict[str, Any], state: str) -> None:
        try:
            await self._store.set_card_index_state(
                UUID(event["tenant_id"]), UUID(event["card_id"]), state
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("knowledge_index_event_has_no_card_identity")


class IndexExecutor(Protocol):
    async def execute(self, event: dict[str, Any]) -> tuple[str, str | None]: ...


class IndexProjectionStore(Protocol):
    async def set_card_index_state(self, tenant_id: UUID, card_id: UUID, state: str) -> None: ...


def _routing_key(event_type: str) -> str:
    if event_type == "knowledge.analysis.requested":
        return KNOWLEDGE_ANALYSIS_ROUTING_KEY
    if event_type == "knowledge.index.requested":
        return "knowledge.index.execute"
    raise ValueError(f"unsupported knowledge event type: {event_type}")
