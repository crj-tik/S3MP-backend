from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from s3mp.audit.domain.events import AuditWriter
from s3mp.files.domain.multipart import (
    MultipartPart,
    MultipartService,
    MultipartSession,
    MultipartStatus,
    ObjectOperation,
    OperationStatus,
)
from s3mp.files.domain.service import FileService, FileValidationError, ObjectMetadata
from s3mp.governance.domain.quota import Quota, QuotaExceededError, QuotaService, ReservationStatus
from s3mp.storage.domain.connection import S3Adapter, S3ConnectionConfig, S3Credentials
from s3mp.storage.domain.policy import StorageCapabilities


class FakeMultipartStore:
    def __init__(self, *, fail_delete: bool = False) -> None:
        self.parts: dict[str, list[MultipartPart]] = {}
        self.fail_delete = fail_delete
        self.aborted: list[str] = []

    async def create_multipart(self, key: str, content_type: str) -> str:
        self.parts["upload"] = []
        return "upload"

    async def upload_part(self, upload_id: str, number: int, body: bytes) -> MultipartPart:
        part = MultipartPart(number, f"etag-{number}", len(body))
        self.parts[upload_id] = [
            item for item in self.parts[upload_id] if item.number != number
        ] + [part]
        return part

    async def list_parts(self, upload_id: str) -> list[MultipartPart]:
        return sorted(self.parts[upload_id], key=lambda item: item.number)

    async def complete_multipart(
        self, upload_id: str, parts: list[MultipartPart]
    ) -> ObjectMetadata:
        return ObjectMetadata(
            "team/object", sum(item.size for item in parts), "application/octet-stream"
        )

    async def abort_multipart(self, upload_id: str) -> None:
        self.aborted.append(upload_id)

    async def copy(self, source_key: str, destination_key: str) -> ObjectMetadata:
        return ObjectMetadata(destination_key, 1, "text/plain")

    async def delete(self, key: str) -> None:
        if self.fail_delete:
            raise RuntimeError("delete unavailable")


def multipart_session() -> MultipartSession:
    return MultipartSession(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "team/object",
        3,
        "application/octet-stream",
        uuid4(),
        datetime.now(UTC) + timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_multipart_is_principal_bound_and_lifecycle_checked() -> None:
    store, service = FakeMultipartStore(), MultipartService(FakeMultipartStore())
    service = MultipartService(store)
    session = await service.create(multipart_session())
    with pytest.raises(FileValidationError):
        await service.add_part(session, uuid4(), 1, b"a")
    session = await service.add_part(session, session.principal_id, 1, b"a")
    session = await service.add_part(session, session.principal_id, 2, b"bc")
    completed, metadata = await service.complete(session, session.principal_id)
    assert completed.status is MultipartStatus.COMPLETED and metadata.content_length == 3
    expired = multipart_session().__class__(
        uuid4(),
        session.tenant_id,
        session.principal_id,
        session.storage_space_id,
        "team/expired",
        1,
        "application/octet-stream",
        uuid4(),
        datetime.now(UTC) - timedelta(seconds=1),
        provider_upload_id="old",
    )
    assert (await service.cleanup_expired([expired], datetime.now(UTC)))[
        0
    ].status is MultipartStatus.EXPIRED
    assert "old" in store.aborted


@pytest.mark.asyncio
async def test_move_partial_failure_and_confirmed_idempotent_batch_delete() -> None:
    service = MultipartService(FakeMultipartStore(fail_delete=True))
    operation = ObjectOperation(uuid4(), uuid4(), uuid4(), "move", "team/a", "team/b")
    result = await service.move(operation)
    assert result.status is OperationStatus.PARTIAL_FAILURE
    with pytest.raises(FileValidationError):
        await service.delete_batch(
            ["team/a"], ["team/b"], uuid4(), tenant_id=uuid4(), principal_id=uuid4()
        )
    result = await service.delete_batch(
        ["team/a"], ["team/a"], uuid4(), tenant_id=uuid4(), principal_id=uuid4()
    )
    assert result.status is OperationStatus.PARTIAL_FAILURE


def test_quota_settlement_release_reconcile_and_append_only_audit() -> None:
    quota_service = QuotaService()
    quota = Quota(uuid4(), uuid4(), None, 10)
    quota, reservation = quota_service.reserve(quota, 5)
    quota, settled = quota_service.settle(quota, reservation, 4)
    assert settled.status is ReservationStatus.SETTLED and quota.used_bytes == 4
    quota, reservation = quota_service.reserve(quota, 3)
    quota, released = quota_service.release(quota, reservation)
    assert released.status is ReservationStatus.RELEASED and quota.reserved_bytes == 0
    assert quota_service.reconcile(quota, 7).used_bytes == 7
    with pytest.raises(QuotaExceededError):
        quota_service.reserve(quota, 20)
    event = AuditWriter().create(
        quota.tenant_id, "file.presigned", "file", details={"url": "secret", "size": 4}
    )
    assert event.details == {"size": 4} and len(AuditWriter.fingerprint("url")) == 64


def test_direct_upload_falls_back_and_disabled_subject_cannot_presign() -> None:
    principal = uuid4()
    active = {principal}
    adapter = S3Adapter(
        S3ConnectionConfig("https://s3.example.test", "region", True),
        S3Credentials("key", "secret"),
    )

    class UnusedStore:
        async def list(self, prefix: str) -> list[ObjectMetadata]:
            raise AssertionError("this test does not access file storage")

        async def head(self, key: str) -> ObjectMetadata | None:
            raise AssertionError("this test does not access file storage")

        async def put(self, key: str, body: bytes, content_type: str) -> ObjectMetadata:
            raise AssertionError("this test does not access file storage")

    service = FileService(
        UnusedStore(), adapter, "bucket", subject_is_active=lambda value: value in active
    )
    assert (
        service.choose_upload_mode(StorageCapabilities(presigned_put=False), direct_requested=True)
        == "proxy"
    )
    session = service.create_upload_session(
        uuid4(), principal, uuid4(), "team/a", "team", 1, "text/plain"
    )
    active.remove(principal)
    with pytest.raises(FileValidationError):
        service.presign_put(session)
