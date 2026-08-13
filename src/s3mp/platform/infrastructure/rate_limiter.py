"""Account login limiter adapter backed by the shared Redis primitive."""

from redis.asyncio import Redis

from s3mp.common.redis_adapters import RedisRateLimiter


class RedisAccountLoginRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._limiter = RedisRateLimiter(redis, limit=5, window_seconds=300)

    async def allow(self, key: str, *, now: float | None = None) -> bool:
        # Redis supplies a server-independent clock through its atomic window
        # operations.  ``now`` exists only for the in-memory test protocol.
        del now
        return await self._limiter.allow("account-login", key)
