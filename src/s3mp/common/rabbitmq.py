"""RabbitMQ connection and topology helpers for asynchronous file operations."""

from collections.abc import Mapping

import aio_pika
from aio_pika.abc import AbstractRobustConnection

EVENT_EXCHANGE = "s3mp.events"
DEAD_LETTER_EXCHANGE = "s3mp.dlx"
FILE_OPERATION_QUEUE = "file.operation.q"
FILE_OPERATION_DLQ = "file.operation.dlq"
FILE_OPERATION_ROUTING_KEY = "file.operation.execute"
KNOWLEDGE_ANALYSIS_QUEUE = "knowledge.analysis.q"
KNOWLEDGE_ANALYSIS_DLQ = "knowledge.analysis.dlq"
KNOWLEDGE_ANALYSIS_ROUTING_KEY = "knowledge.analysis.execute"
KNOWLEDGE_INDEX_QUEUE = "knowledge.index.q"
KNOWLEDGE_INDEX_DLQ = "knowledge.index.dlq"
KNOWLEDGE_INDEX_ROUTING_KEY = "knowledge.index.execute"
RETRY_DELAYS: Mapping[str, int] = {
    "file.operation.retry.5s": 5_000,
    "file.operation.retry.1m": 60_000,
    "file.operation.retry.5m": 300_000,
    "file.operation.retry.15m": 900_000,
}
KNOWLEDGE_RETRY_DELAYS: Mapping[str, int] = {
    "knowledge.retry.5s": 5_000,
    "knowledge.retry.1m": 60_000,
    "knowledge.retry.5m": 300_000,
}


async def connect_rabbitmq(url: str) -> AbstractRobustConnection:
    return await aio_pika.connect_robust(url)


async def declare_file_operation_topology(
    connection: AbstractRobustConnection, *, prefetch: int = 10
) -> None:
    """Declare durable broker entities; calls are intentionally idempotent."""
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=prefetch)
    events = await channel.declare_exchange(
        EVENT_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
    )
    dlx = await channel.declare_exchange(
        DEAD_LETTER_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
    )
    arguments = {"x-queue-type": "quorum", "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE}
    main = await channel.declare_queue(FILE_OPERATION_QUEUE, durable=True, arguments=arguments)
    await main.bind(events, routing_key=FILE_OPERATION_ROUTING_KEY)
    await channel.declare_queue(
        FILE_OPERATION_DLQ, durable=True, arguments={"x-queue-type": "quorum"}
    )
    dlq = await channel.get_queue(FILE_OPERATION_DLQ)
    await dlq.bind(dlx, routing_key=FILE_OPERATION_ROUTING_KEY)
    for name, ttl in RETRY_DELAYS.items():
        retry = await channel.declare_queue(
            name,
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-message-ttl": ttl,
                "x-dead-letter-exchange": EVENT_EXCHANGE,
                "x-dead-letter-routing-key": FILE_OPERATION_ROUTING_KEY,
            },
        )
        await retry.bind(events, routing_key=name)
    await channel.close()


async def declare_knowledge_topology(
    connection: AbstractRobustConnection, *, prefetch: int = 2
) -> None:
    """Declare isolated durable queues for extraction and ES projection."""
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=prefetch)
    events = await channel.declare_exchange(
        EVENT_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
    )
    dead_letters = await channel.declare_exchange(
        DEAD_LETTER_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
    )
    for queue_name, dlq_name, routing_key in (
        (KNOWLEDGE_ANALYSIS_QUEUE, KNOWLEDGE_ANALYSIS_DLQ, KNOWLEDGE_ANALYSIS_ROUTING_KEY),
        (KNOWLEDGE_INDEX_QUEUE, KNOWLEDGE_INDEX_DLQ, KNOWLEDGE_INDEX_ROUTING_KEY),
    ):
        queue = await channel.declare_queue(
            queue_name,
            durable=True,
            arguments={"x-queue-type": "quorum", "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE},
        )
        await queue.bind(events, routing_key=routing_key)
        dlq = await channel.declare_queue(
            dlq_name, durable=True, arguments={"x-queue-type": "quorum"}
        )
        await dlq.bind(dead_letters, routing_key=routing_key)
        for retry_name, ttl in KNOWLEDGE_RETRY_DELAYS.items():
            retry = await channel.declare_queue(
                f"{queue_name}.{retry_name.rsplit('.', 1)[-1]}",
                durable=True,
                arguments={
                    "x-queue-type": "quorum",
                    "x-message-ttl": ttl,
                    "x-dead-letter-exchange": EVENT_EXCHANGE,
                    "x-dead-letter-routing-key": routing_key,
                },
            )
            await retry.bind(events, routing_key=f"{routing_key}.{retry_name.rsplit('.', 1)[-1]}")
    await channel.close()
