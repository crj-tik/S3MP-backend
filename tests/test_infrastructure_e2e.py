"""Real infrastructure connectivity tests (pg / redis / minio must be running)."""

from sqlalchemy import text

from _infrastructure import TEST_REDIS_URL, real_engine, real_settings
from s3mp.common.redis import create_redis
from s3mp.storage.infrastructure.minio import MinioObjectStorageAdapter


async def test_postgresql_connectivity() -> None:
    engine = real_engine()
    try:
        async with engine.connect() as conn:
            value = await conn.scalar(text("SELECT 1"))
        assert value == 1
    finally:
        await engine.dispose()


async def test_redis_connectivity() -> None:
    redis = create_redis(TEST_REDIS_URL)
    try:
        assert await redis.ping() is True
    finally:
        await redis.aclose()


async def test_minio_readiness_probe() -> None:
    adapter = MinioObjectStorageAdapter(real_settings())
    await adapter.readiness_probe()  # raises on failure


async def test_minio_put_head_delete_round_trip() -> None:
    adapter = MinioObjectStorageAdapter(real_settings())
    key = "infrastructure-test/round-trip.txt"
    try:
        metadata = await adapter.put(key, b"hello-s3mp", "text/plain")
        assert metadata.content_length == len(b"hello-s3mp")
        head = await adapter.head(key)
        assert head is not None
        assert head.content_length == len(b"hello-s3mp")
    finally:
        await adapter.delete(key)
    assert await adapter.head(key) is None
