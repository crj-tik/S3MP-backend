"""Best-effort Redis wake-up hints; PostgreSQL remains the work source of truth."""

import logging
from collections.abc import Awaitable
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from s3mp.common.logging import log_event

CHANNEL = "s3mp:file-work"
logger = logging.getLogger(__name__)


class RedisWorkSignal:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def notify(self) -> bool:
        try:
            await cast(Awaitable[int], self._redis.lpush(CHANNEL, "ready"))
            await cast(Awaitable[int], self._redis.ltrim(CHANNEL, 0, 99))
            return True
        except RedisError:
            log_event(
                logger,
                logging.WARNING,
                "redis.work_signal.notify_failed",
                layer="infrastructure",
                dependency="redis",
                dependency_operation="work_signal_notify",
                outcome="failed",
            )
            return False

    async def wait(self, timeout_seconds: float) -> bool:
        try:
            result = await cast(
                Awaitable[list[Any] | None],
                self._redis.blpop([CHANNEL], timeout=max(1, int(timeout_seconds))),
            )
            return result is not None
        except RedisError:
            log_event(
                logger,
                logging.WARNING,
                "redis.work_signal.wait_failed",
                layer="infrastructure",
                dependency="redis",
                dependency_operation="work_signal_wait",
                outcome="failed",
            )
            return False
