"""Real infrastructure connectivity tests (pg / redis / minio must be running)."""

from uuid import uuid4

from sqlalchemy import text

from _infrastructure import TEST_REDIS_URL, real_engine, real_settings
from s3mp.common.redis import create_redis
from s3mp.storage.domain.policy import ProviderTarget, derive_provider_target
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
    target = ProviderTarget("s3mp-dev", "v1/infrastructure-test/round-trip.txt")
    try:
        metadata = await adapter.put(target, b"hello-s3mp", "text/plain")
        assert metadata.content_length == len(b"hello-s3mp")
        head = await adapter.head(target)
        assert head is not None
        assert head.content_length == len(b"hello-s3mp")
    finally:
        await adapter.delete(target)
    assert await adapter.head(target) is None


async def test_minio_tenant_targets_cannot_collide_or_mutate_each_other() -> None:
    adapter = MinioObjectStorageAdapter(real_settings())
    tenant_a, tenant_b, space_a, space_b = uuid4(), uuid4(), uuid4(), uuid4()
    target_a = derive_provider_target(
        tenant_id=tenant_a,
        storage_space_id=space_a,
        bucket="s3mp-dev",
        relative_key="team/report.txt",
    )
    target_b = derive_provider_target(
        tenant_id=tenant_b,
        storage_space_id=space_b,
        bucket="s3mp-dev",
        relative_key="team/report.txt",
    )
    copied_a = ProviderTarget(target_a.bucket, target_a.key + ".copy")
    assert target_a.key != target_b.key
    try:
        await adapter.put(target_a, b"tenant-a", "text/plain")
        await adapter.put(target_b, b"tenant-b", "text/plain")
        await adapter.copy(target_a, copied_a)
        assert (await adapter.head(target_a)).content_length == len(b"tenant-a")  # type: ignore[union-attr]
        assert (await adapter.head(target_b)).content_length == len(b"tenant-b")  # type: ignore[union-attr]
        await adapter.delete(target_a)
        assert await adapter.head(target_a) is None
        assert (await adapter.head(target_b)).content_length == len(b"tenant-b")  # type: ignore[union-attr]
        url_a, url_b = (
            await adapter.presign_get(copied_a, 60),
            await adapter.presign_get(target_b, 60),
        )
        assert copied_a.key in url_a and target_b.key in url_b
        assert target_b.key not in url_a and copied_a.key not in url_b
    finally:
        for target in (target_a, target_b, copied_a):
            await adapter.delete(target)
