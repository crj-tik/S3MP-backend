from redis.asyncio import Redis

from _infrastructure import TEST_REDIS_URL
from s3mp.common.redis import create_redis
from s3mp.files.infrastructure.work_signal import CHANNEL, RedisWorkSignal


async def test_real_redis_wakeup_hint_round_trip() -> None:
    redis = create_redis(TEST_REDIS_URL)
    try:
        await redis.delete(CHANNEL)
        signal = RedisWorkSignal(redis)
        assert await signal.notify()
        assert await signal.wait(1)
    finally:
        await redis.delete(CHANNEL)
        await redis.aclose()


async def test_redis_unavailable_degrades_to_polling() -> None:
    redis = Redis.from_url(
        "redis://127.0.0.1:1/15",
        decode_responses=True,
        socket_connect_timeout=0.1,
        socket_timeout=0.1,
    )
    try:
        signal = RedisWorkSignal(redis)
        assert not await signal.notify()
        assert not await signal.wait(1)
    finally:
        await redis.aclose()
