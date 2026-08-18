from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from s3mp.files.domain.service import (
    FileService,
    FileValidationError,
    ObjectMetadata,
    SecureCursorCodec,
)
from s3mp.storage.domain.connection import S3Adapter, S3ConnectionConfig, S3Credentials
from s3mp.storage.domain.policy import (
    AuthorizedCommand,
    StorageCapabilities,
    StorageOperation,
    StoragePolicyError,
    StorageUnsupportedError,
    acceptance_prefix_round_trip,
    build_authorized_request,
    canonical_object_key,
    read_probe,
)


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, ObjectMetadata] = {}

    async def list(self, prefix: str) -> list[ObjectMetadata]:
        return list(self.objects.values())

    async def head(self, key: str) -> ObjectMetadata | None:
        return self.objects.get(key)

    async def put(self, key: str, body: bytes, content_type: str) -> ObjectMetadata:
        metadata = ObjectMetadata(key, len(body), content_type, etag="multipart-etag-2")
        self.objects[key] = metadata
        return metadata


class ProbeStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def head(self, bucket: str, key: str) -> object:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]

    async def put(self, bucket: str, key: str, body: bytes, content_type: str) -> object:
        self.objects[key] = body
        return None

    async def get(self, bucket: str, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, bucket: str, key: str) -> object:
        self.objects.pop(key, None)
        return None


@pytest.fixture
def service() -> FileService:
    adapter = S3Adapter(
        S3ConnectionConfig("https://s3.example.test", "cn-test-1", True),
        S3Credentials("AKIA_TEST", "secret"),
    )
    return FileService(FakeStore(), adapter, "bucket", max_presign_ttl=120)


def test_canonical_key_and_immutable_authorized_command() -> None:
    for invalid in ("/team/a", "team//a", "team/../a", "team/%2f/a", "team\\a", "team/a\x00"):
        with pytest.raises(StoragePolicyError):
            canonical_object_key(invalid)
    command = AuthorizedCommand(uuid4(), uuid4(), StorageOperation.HEAD, "bucket", "team/a")
    with pytest.raises(FrozenInstanceError):
        command.object_key = "other"  # type: ignore[misc]


def test_capability_allowlist_is_connection_scoped() -> None:
    adapter = S3Adapter(
        S3ConnectionConfig("https://s3.example.test", "cn-test-1", True),
        S3Credentials("key", "secret"),
    )
    command = AuthorizedCommand(uuid4(), uuid4(), StorageOperation.DELETE, "bucket", "team/a")
    with pytest.raises(StorageUnsupportedError) as error:
        build_authorized_request(adapter, command, StorageCapabilities())
    assert error.value.code == "storage_operation_unsupported"


@pytest.mark.asyncio
async def test_probes_are_read_only_or_confined_to_test_key() -> None:
    store = ProbeStore()
    assert not await read_probe(store, "bucket", "missing")
    assert await acceptance_prefix_round_trip(store, "bucket", "s3mp-test/probe")
    assert "s3mp-test/probe" not in store.objects


@pytest.mark.asyncio
async def test_file_service_authorizes_prefix_and_validates_direct_upload(
    service: FileService,
) -> None:
    store = service._store
    assert isinstance(store, FakeStore)
    store.objects["team/a.txt"] = ObjectMetadata("team/a.txt", 1, "text/plain", etag="not-an-md5")
    store.objects["team2/leak.txt"] = ObjectMetadata("team2/leak.txt", 1, "text/plain")
    assert [item.key for item in await service.list_authorized("team")] == ["team/a.txt"]
    with pytest.raises(FileValidationError):
        service.create_upload_session(
            uuid4(), uuid4(), uuid4(), "team/new", "team", -1, "text/plain"
        )
    with pytest.raises(FileValidationError):
        service.create_upload_session(
            uuid4(), uuid4(), uuid4(), "team/new", "team", 2, ""
        )


@pytest.mark.asyncio
async def test_direct_upload_preserves_declared_metadata(service: FileService) -> None:
    session = service.create_upload_session(
        uuid4(), uuid4(), uuid4(), "team/quota.txt", "team", 3, "text/plain"
    )
    assert session.declared_length == 3


@pytest.mark.asyncio
async def test_presigned_upload_completion_download_and_secure_cursor(service: FileService) -> None:
    tenant, principal, space = uuid4(), uuid4(), uuid4()
    session = service.create_upload_session(
        tenant, principal, space, "team/data.csv", "team", 2, "text/csv"
    )
    put = service.presign_put(session, ttl_seconds=60)
    assert put.method == "PUT" and "X-Amz-Signature=" in put.url
    assert "secret" not in put.url and not hasattr(session, "url")
    store = service._store
    assert isinstance(store, FakeStore)
    await store.put("team/data.csv", b"ok", "text/csv")
    completed, metadata = await service.complete_upload(session)
    assert completed.status == "completed" and metadata.etag == "multipart-etag-2"
    get, fingerprint = service.presign_get("team/data.csv", "team", ttl_seconds=60)
    assert get.method == "GET" and len(fingerprint) == 64
    with pytest.raises(FileValidationError):
        service.presign_get("team2/data.csv", "team")
    with pytest.raises(FileValidationError):
        service.presign_get("team/data.csv", "team", ttl_seconds=121)
    codec = SecureCursorCodec(b"cursor-signing-secret-32-bytes-long")
    token = codec.encode(tenant, principal, "team/data.csv", "team")
    assert codec.decode(token, tenant, principal, "team") == "team/data.csv"
    with pytest.raises(FileValidationError):
        codec.decode(token, tenant, uuid4(), "team")
