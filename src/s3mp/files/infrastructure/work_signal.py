"""Best-effort Redis wake-up hints; PostgreSQL remains the work source of truth."""

from redis.asyncio import Redis
from redis.exceptions import RedisError

CHANNEL = "s3mp:file-work"


class RedisWorkSignal:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def notify(self) -> bool:
        try:
            await self._redis.lpush(CHANNEL, "ready")
            await self._redis.ltrim(CHANNEL, 0, 99)
            return True
        except RedisError:
            return False

    async def wait(self, timeout_seconds: float) -> bool:
        try:
            result = await self._redis.blpop(CHANNEL, timeout=max(1, int(timeout_seconds)))
            return result is not None
        except RedisError:
            return False
