"""Redis-backed idempotency storage with TTL."""

import json
from typing import Any
from uuid import UUID

from redis.asyncio import Redis


class RedisIdempotencyStore:
    def __init__(self, redis: Redis, *, ttl_seconds: int = 86400) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def _key(self, fingerprint: str) -> str:
        return f"s3mp:idem:{fingerprint}"

    async def get(self, fingerprint: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._key(fingerprint))
        if raw is None:
            return None
        return json.loads(raw)  # type: ignore[no-any-return]

    async def put(self, fingerprint: str, result: dict[str, Any]) -> None:
        await self._redis.setex(self._key(fingerprint), self._ttl, json.dumps(result, default=str))


class RedisRateLimiter:
    """Redis-backed sliding-window rate limiter."""

    def __init__(self, redis: Redis, *, limit: int = 60, window_seconds: int = 60) -> None:
        self._redis = redis
        self._limit = limit
        self._window = window_seconds

    def _key(self, scope: str, identifier: str) -> str:
        return f"s3mp:rate:{scope}:{identifier}"

    async def allow(self, scope: str, identifier: str) -> bool:
        key = self._key(scope, identifier)
        import time

        now = time.time()
        cutoff = now - self._window
        async with self._redis.pipeline() as pipe:
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, self._window)
            _, count, _, _ = await pipe.execute()
        return int(count) < self._limit


class RedisOutboxAdapter:
    """Redis-backed outbox coordination with retry-safe ownership."""

    def __init__(self, redis: Redis, *, lease_seconds: int = 30) -> None:
        self._redis = redis
        self._lease = lease_seconds

    def _list_key(self, topic: str) -> str:
        return f"s3mp:outbox:list:{topic}"

    def _msg_key(self, msg_id: UUID) -> str:
        return f"s3mp:outbox:msg:{msg_id}"

    async def enqueue(self, topic: str, payload: dict[str, Any]) -> None:
        import time

        msg = {"topic": topic, "payload": payload, "ts": time.time()}
        await self._redis.rpush(self._list_key(topic), json.dumps(msg, default=str))  # type: ignore[misc]

    async def dequeue(self, topic: str, batch_size: int = 10) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        key = self._list_key(topic)
        for _ in range(batch_size):
            raw = await self._redis.lpop(key)  # type: ignore[misc]
            if raw is None:
                break
            msg = json.loads(raw)
            lease_key = self._msg_key(
                UUID(msg["payload"].get("id", "00000000-0000-0000-0000-000000000000"))
            )
            acquired = await self._redis.set(lease_key, "1", nx=True, ex=self._lease)
            if acquired:
                results.append(msg)
        return results

    async def ack(self, msg_id: UUID) -> None:
        await self._redis.delete(self._msg_key(msg_id))

    async def nack(self, msg_id: UUID, reason: str) -> None:
        await self._redis.delete(self._msg_key(msg_id))
