from uuid import uuid4

import pytest

from s3mp.audit.domain.events import AuditWriter
from s3mp.files.domain.file_operations import (
    ObjectMutationService,
    ObjectOperation,
    OperationStatus,
)
from s3mp.files.domain.service import FileService, FileValidationError, ObjectMetadata
from s3mp.governance.domain.quota import Quota, QuotaExceededError, QuotaService, ReservationStatus
from s3mp.storage.domain.connection import S3Adapter, S3ConnectionConfig, S3Credentials


class FakeMultipartStore:
    def __init__(self, *, fail_delete: bool = False) -> None:
        self.fail_delete = fail_delete

    async def copy(self, source_key: str, destination_key: str) -> ObjectMetadata:
        return ObjectMetadata(destination_key, 1, "text/plain")

    async def delete(self, key: str) -> None:
        if self.fail_delete:
            raise RuntimeError("delete unavailable")


@pytest.mark.asyncio
async def test_move_partial_failure_and_confirmed_idempotent_batch_delete() -> None:
    service = ObjectMutationService(FakeMultipartStore(fail_delete=True))
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


def test_direct_upload_requires_active_subject_for_presign() -> None:
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
    session = service.create_upload_session(
        uuid4(), principal, uuid4(), "team/a", "team", 1, "text/plain"
    )
    active.remove(principal)
    with pytest.raises(FileValidationError):
        service.presign_put(session)
