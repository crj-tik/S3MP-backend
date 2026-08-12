"""S3 bucket acceptance and multi-tenant security drill tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from s3mp.authorization.domain.delegation import DelegationScope, validate_delegated_scope
from s3mp.authorization.domain.evaluator import (
    Binding,
    Decision,
    evaluate,
)
from s3mp.files.domain.multipart import (
    MultipartService,
    MultipartSession,
    MultipartStatus,
    ObjectOperation,
    OperationStatus,
)
from s3mp.files.domain.service import (
    FileService,
    FileValidationError,
    ObjectMetadata,
    SecureCursorCodec,
    UploadSession,
)
from s3mp.storage.domain.connection import (
    S3Adapter,
    S3ConnectionConfig,
    S3Credentials,
    SigV4Signer,
    path_style_url,
)
from s3mp.storage.domain.policy import (
    AuthorizedCommand,
    StorageCapabilities,
    StorageOperation,
    StoragePolicyError,
    StorageUnsupportedError,
    acceptance_prefix_round_trip,
    build_authorized_request,
    canonical_object_key,
    choose_upload_mode,
    read_probe,
)

# ── helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime(2026, 8, 1, tzinfo=UTC)


def _config(**kwargs: object) -> S3ConnectionConfig:
    defaults = {
        "endpoint": "https://s3.example.com",
        "region": "us-east-1",
        "path_style": True,
    }
    return S3ConnectionConfig(**{**defaults, **kwargs})


def _adapter() -> S3Adapter:
    return S3Adapter(_config(), S3Credentials("AKID", "secret"))


# ── 10.3: S3 Bucket Acceptance ───────────────────────────────────────────────

class TestS3Connection:
    """Region, TLS, gateway, presigned TTL, and network conditions."""

    def test_requires_https(self) -> None:
        with pytest.raises(ValueError, match="TLS"):
            S3ConnectionConfig(endpoint="http://s3.example.com", region="us-east-1", path_style=True)

    def test_requires_endpoint_and_region(self) -> None:
        with pytest.raises(ValueError, match="endpoint and region"):
            S3ConnectionConfig(endpoint="https://", region=" ", path_style=True)

    def test_presigned_ttl_within_service_limit(self) -> None:
        with pytest.raises(ValueError, match="presigned TTL"):
            S3ConnectionConfig(
                endpoint="https://s3.example.com", region="us-east-1", path_style=True,
                max_presign_ttl_seconds=0,
            )
        with pytest.raises(ValueError, match="presigned TTL"):
            S3ConnectionConfig(
                endpoint="https://s3.example.com", region="us-east-1", path_style=True,
                max_presign_ttl_seconds=3601,
            )

    def test_path_style_url_construction(self) -> None:
        config = _config(path_style=True)
        url = path_style_url(config, "my-bucket", "folder/file.txt")
        assert "my-bucket" in url
        assert "folder/file.txt" in url
        assert url.startswith("https://s3.example.com/my-bucket/")

    def test_path_style_rejects_slash_in_bucket(self) -> None:
        with pytest.raises(ValueError, match="bucket"):
            path_style_url(_config(), "bad/bucket", "key")

    def test_sigv4_request_is_explicit_and_signed(self) -> None:
        signer = SigV4Signer(S3Credentials("AKID", "secret"))
        signed = signer.sign(
            "GET", "https://s3.example.com/bucket/key",
            region="us-east-1", now=_now(),
        )
        assert "authorization" in signed.headers
        assert "AWS4-HMAC-SHA256" in signed.headers["authorization"]
        assert signed.headers["host"] == "s3.example.com"
        assert "x-amz-content-sha256" in signed.headers
        assert "x-amz-date" in signed.headers

    def test_presigned_url_contains_required_params(self) -> None:
        signer = SigV4Signer(S3Credentials("AKID", "secret"))
        presigned = signer.presign(
            "GET", "https://s3.example.com/bucket/key",
            region="us-east-1", expires_seconds=900, now=_now(),
        )
        assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in presigned.url
        assert "X-Amz-Credential=" in presigned.url
        assert "X-Amz-Expires=900" in presigned.url
        assert "X-Amz-Signature=" in presigned.url
        assert presigned.expires_at > _now()

    def test_adapter_presign_respects_connection_ttl_limit(self) -> None:
        adapter = S3Adapter(
            _config(max_presign_ttl_seconds=600),
            S3Credentials("AKID", "secret"),
        )
        with pytest.raises(ValueError, match="TTL exceeds"):
            adapter.presign_request("GET", "bucket", "key", expires_seconds=900)


class TestS3Capabilities:
    """Capability flags, allowlist, and connection-level compatibility switches."""

    def test_operation_allowlist_is_connection_scoped(self) -> None:
        caps = StorageCapabilities(
            list_objects=True, head_object=True, presigned_get=True,
            proxy_upload=False, presigned_put=False,
            multipart=False, copy_object=False, delete_object=False,
        )
        assert caps.supports(StorageOperation.LIST)
        assert caps.supports(StorageOperation.HEAD)
        assert caps.supports(StorageOperation.GET)
        assert not caps.supports(StorageOperation.PUT)
        assert not caps.supports(StorageOperation.DELETE)

    def test_unsupported_operation_is_rejected(self) -> None:
        caps = StorageCapabilities(delete_object=False, copy_object=False, multipart=False)
        cmd = AuthorizedCommand(uuid4(), uuid4(), StorageOperation.DELETE, "bucket", "deleteme.txt")
        with pytest.raises(StorageUnsupportedError, match="disabled"):
            build_authorized_request(_adapter(), cmd, caps)

    def test_choose_upload_mode_direct_vs_proxy(self) -> None:
        proxy_only = StorageCapabilities(proxy_upload=True, presigned_put=False)
        assert choose_upload_mode(proxy_only, direct_requested=True) == "proxy"

        direct_ok = StorageCapabilities(proxy_upload=True, presigned_put=True)
        assert choose_upload_mode(direct_ok, direct_requested=True) == "direct"
        assert choose_upload_mode(direct_ok, direct_requested=False) == "proxy"

        neither = StorageCapabilities(proxy_upload=False, presigned_put=False)
        with pytest.raises(StorageUnsupportedError):
            choose_upload_mode(neither, direct_requested=True)

    def test_read_probe_is_non_destructive(self) -> None:
        class FailingProbe:
            async def head(self, bucket: str, key: str) -> object:
                raise ConnectionError("unreachable")

        async def run():
            return await read_probe(FailingProbe(), "bucket", "key")
        import asyncio
        result = asyncio.run(run())
        assert result is False

    def test_acceptance_prefix_round_trip(self) -> None:
        stored: dict[str, bytes] = {}

        class InMemoryProbe:
            async def head(self, bucket: str, key: str) -> object:
                return None

            async def put(self, bucket: str, key: str, body: bytes, content_type: str) -> object:
                stored[key] = body
                return None

            async def get(self, bucket: str, key: str) -> bytes:
                return stored[key]

            async def delete(self, bucket: str, key: str) -> object:
                stored.pop(key, None)
                return None

        async def run():
            return await acceptance_prefix_round_trip(
                InMemoryProbe(), "bucket", "test-prefix/probe-key"
            )
        import asyncio
        result = asyncio.run(run())
        assert result is True
        assert not stored  # probe key cleaned up


class TestFileOperations:
    """Read, write, presigned, multipart, copy, and delete."""

    def test_canonical_key_rejects_unsafe_paths(self) -> None:
        for bad in ["/root", "..\\escape", "key\x00null", "key%2Fencoded"]:
            with pytest.raises(StoragePolicyError):
                canonical_object_key(bad)

    def test_authorized_command_requires_bucket(self) -> None:
        with pytest.raises(StoragePolicyError, match="bucket"):
            AuthorizedCommand(uuid4(), uuid4(), StorageOperation.GET, "", "key")

    def test_authorized_command_allows_empty_key_for_list(self) -> None:
        cmd = AuthorizedCommand(uuid4(), uuid4(), StorageOperation.LIST, "bucket")
        assert cmd.object_key == ""

    def test_file_service_authorizes_key_within_prefix(self) -> None:
        class NoopStore:
            async def list(self, prefix: str) -> list[ObjectMetadata]:
                return []
            async def head(self, key: str) -> ObjectMetadata | None:
                return None
            async def put(self, key: str, body: bytes, content_type: str) -> ObjectMetadata:
                return ObjectMetadata(key, len(body), content_type)

        svc = FileService(NoopStore(), _adapter(), "bucket", max_presign_ttl=900)
        with pytest.raises(FileValidationError, match="outside authorized prefix"):
            svc.presign_get("other/file.txt", "team")

    def test_presigned_get_returns_fingerprint(self) -> None:
        class NoopStore:
            async def list(self, prefix: str) -> list[ObjectMetadata]:
                return []
            async def head(self, key: str) -> ObjectMetadata | None:
                return None
            async def put(self, key: str, body: bytes, content_type: str) -> ObjectMetadata:
                return ObjectMetadata(key, len(body), content_type)

        svc = FileService(NoopStore(), _adapter(), "bucket", max_presign_ttl=900)
        _, fingerprint = svc.presign_get("team/file.txt", "team", ttl_seconds=300)
        assert len(fingerprint) == 64  # SHA-256 hex

    def test_disabled_subject_cannot_create_upload(self) -> None:
        svc = FileService(
            None, _adapter(), "bucket",  # type: ignore[arg-type]
            subject_is_active=lambda _pid: False,
        )
        with pytest.raises(FileValidationError, match="disabled principal"):
            svc.create_upload_session(
                uuid4(), uuid4(), uuid4(), "team/file.txt", "team", 100, "text/plain",
            )

    def test_secure_cursor_binds_tenant_principal_and_prefix(self) -> None:
        codec = SecureCursorCodec(b"x" * 16)
        tenant = uuid4()
        principal = uuid4()
        token = codec.encode(tenant, principal, "file-99", "team/docs")
        assert codec.decode(token, tenant, principal, "team/docs") == "file-99"
        with pytest.raises(FileValidationError):
            codec.decode(token, uuid4(), principal, "team/docs")
        with pytest.raises(FileValidationError):
            codec.decode(token, tenant, principal, "other")

    def test_upload_session_completion_validates_metadata(self) -> None:
        head_result: ObjectMetadata | None = None

        class VerifyingStore:
            async def list(self, prefix: str) -> list[ObjectMetadata]:
                return []
            async def head(self, key: str) -> ObjectMetadata | None:
                return head_result
            async def put(self, key: str, body: bytes, content_type: str) -> ObjectMetadata:
                return ObjectMetadata(key, len(body), content_type)

        svc = FileService(VerifyingStore(), _adapter(), "bucket")
        session = UploadSession(
            uuid4(), uuid4(), uuid4(), uuid4(), "team/file.txt", 100, "text/plain",
            datetime.now(UTC) + timedelta(hours=1),
        )
        # Object not found
        head_result = None
        with pytest.raises(FileValidationError, match="metadata"):
            import asyncio
            asyncio.run(svc.complete_upload(session))

        # Object size mismatch
        head_result = ObjectMetadata("team/file.txt", 200, "text/plain")
        with pytest.raises(FileValidationError, match="metadata"):
            asyncio.run(svc.complete_upload(session))


class TestMultipartLifecycle:
    """Multipart session creation, part upload, completion, abort, and cleanup."""

    def test_multipart_session_is_principal_bound(self) -> None:
        store_calls: list[str] = []

        class RecordingStore:
            async def create_multipart(self, key: str, content_type: str) -> str:
                store_calls.append("create")
                return "upload-1"
            async def upload_part(self, upload_id: str, number: int, body: bytes):
                return None
            async def list_parts(self, upload_id: str):
                return []
            async def complete_multipart(self, upload_id: str, parts):
                return ObjectMetadata("key", 100, "text/plain")
            async def abort_multipart(self, upload_id: str) -> None:
                store_calls.append("abort")
            async def copy(self, source_key: str, destination_key: str):
                return ObjectMetadata(destination_key, 100, "text/plain")
            async def delete(self, key: str) -> None:
                pass

        svc = MultipartService(RecordingStore())
        session = MultipartSession(
            uuid4(), uuid4(), uuid4(), uuid4(), "team/file.bin", 100, "application/octet-stream",
            uuid4(), datetime.now(UTC) + timedelta(hours=1),
        )

        async def run():
            created = await svc.create(session)
            assert created.provider_upload_id == "upload-1"
            # Cross-principal access rejected
            with pytest.raises(FileValidationError, match="different principal"):
                await svc.add_part(created, uuid4(), 1, b"x" * 100)
            # Correct principal
            with pytest.raises(FileValidationError, match="invalid multipart part"):
                await svc.add_part(created, session.principal_id, 0, b"x" * 100)
            # Abort
            aborted = await svc.abort(created, session.principal_id)
            assert aborted.status is MultipartStatus.ABORTED

        import asyncio
        asyncio.run(run())

    def test_cleanup_expired_sessions(self) -> None:
        aborted: list[str] = []

        class CleanupStore:
            async def create_multipart(self, key: str, content_type: str) -> str:
                return "upload-1"
            async def upload_part(self, upload_id: str, number: int, body: bytes):
                return None
            async def list_parts(self, upload_id: str):
                return []
            async def complete_multipart(self, upload_id: str, parts):
                return ObjectMetadata("key", 100, "text/plain")
            async def abort_multipart(self, upload_id: str) -> None:
                aborted.append(upload_id)
            async def copy(self, source_key: str, destination_key: str):
                return ObjectMetadata(destination_key, 100, "text/plain")
            async def delete(self, key: str) -> None:
                pass

        svc = MultipartService(CleanupStore())
        expired = MultipartSession(
            uuid4(), uuid4(), uuid4(), uuid4(), "old.bin", 100, "text/plain",
            uuid4(), _now() - timedelta(hours=1), provider_upload_id="upload-old",
        )
        active = MultipartSession(
            uuid4(), uuid4(), uuid4(), uuid4(), "new.bin", 100, "text/plain",
            uuid4(), _now() + timedelta(hours=1), provider_upload_id="upload-new",
        )

        async def run():
            cleaned = await svc.cleanup_expired([expired, active], _now())
            assert len(cleaned) == 1
            assert cleaned[0].status is MultipartStatus.EXPIRED
            assert "upload-old" in aborted
            assert "upload-new" not in aborted

        import asyncio
        asyncio.run(run())

    def test_move_partial_failure_and_batch_delete_confirmation(self) -> None:
        delete_called: list[str] = []

        class MoveStore:
            async def create_multipart(self, key: str, content_type: str) -> str:
                return "upload-1"
            async def upload_part(self, upload_id: str, number: int, body: bytes):
                return None
            async def list_parts(self, upload_id: str):
                return []
            async def complete_multipart(self, upload_id: str, parts):
                return ObjectMetadata("key", 100, "text/plain")
            async def abort_multipart(self, upload_id: str) -> None:
                pass
            async def copy(self, source_key: str, destination_key: str) -> ObjectMetadata:
                return ObjectMetadata(destination_key, 100, "text/plain")
            async def delete(self, key: str) -> None:
                delete_called.append(key)

        svc = MultipartService(MoveStore())

        async def run():
            # Successful move
            op = ObjectOperation(uuid4(), uuid4(), uuid4(), "move", "src/a.txt", "dst/a.txt")
            result = await svc.move(op)
            assert result.status is OperationStatus.COMPLETED
            assert "src/a.txt" in delete_called

            # Batch delete with mismatch
            op_id = uuid4()
            with pytest.raises(FileValidationError, match="confirmation"):
                await svc.delete_batch(["a.txt", "b.txt"], ["a.txt"], op_id, tenant_id=uuid4(), principal_id=uuid4())

        import asyncio
        asyncio.run(run())


# ── 10.4: Multi-tenant Security Drills ───────────────────────────────────────

class TestIDORAndDirectoryTraversal:
    """Cross-tenant IDOR, directory bypass, and path traversal attacks."""

    def test_cross_tenant_key_rejected(self) -> None:
        """Other tenant resource ID must be rejected without leaking existence."""
        codec = SecureCursorCodec(b"x" * 16)
        tenant_a = uuid4()
        principal = uuid4()
        token = codec.encode(tenant_a, principal, "file-1", "docs")
        # Different tenant tries to decode
        with pytest.raises(FileValidationError, match="invalid cursor"):
            codec.decode(token, uuid4(), principal, "docs")

    def test_directory_traversal_rejected(self) -> None:
        for path in ["../escape", "..\\escape", "team/../private", "team//reports"]:
            with pytest.raises((StoragePolicyError, ValueError)):
                canonical_object_key(path)

    def test_prefix_bypass_rejected(self) -> None:
        """A key outside the authorized prefix must be rejected."""
        class NoopStore:
            async def list(self, prefix: str) -> list[ObjectMetadata]:
                return []
            async def head(self, key: str) -> ObjectMetadata | None:
                return None
            async def put(self, key: str, body: bytes, content_type: str) -> ObjectMetadata:
                return ObjectMetadata(key, len(body), content_type)

        svc = FileService(NoopStore(), _adapter(), "bucket")
        # team/private is not within team/public
        with pytest.raises(FileValidationError, match="outside authorized prefix"):
            svc.presign_get("team/private/secrets.txt", "team/public")

    def test_similar_prefix_not_authorized(self) -> None:
        """team-a is not a child of team."""
        class NoopStore:
            async def list(self, prefix: str) -> list[ObjectMetadata]:
                return []
            async def head(self, key: str) -> ObjectMetadata | None:
                return None
            async def put(self, key: str, body: bytes, content_type: str) -> ObjectMetadata:
                return ObjectMetadata(key, len(body), content_type)

        svc = FileService(NoopStore(), _adapter(), "bucket")
        with pytest.raises(FileValidationError, match="outside authorized prefix"):
            svc.presign_get("team-a/file.txt", "team")


class TestDelegationAndAPIKey:
    """Delegation boundaries, API key scope, and revocation."""

    def test_delegation_must_be_subset_of_grantor(self) -> None:
        delegator = DelegationScope(frozenset({"files.read", "files.write"}), "team/docs")
        # Valid: subset permission, narrower prefix
        validate_delegated_scope(
            DelegationScope(frozenset({"files.read"}), "team/docs/reports"), delegator
        )
        # Invalid: permission not in delegator's set
        with pytest.raises(ValueError, match="exceed"):
            validate_delegated_scope(
                DelegationScope(frozenset({"files.admin"}), "team/docs"), delegator
            )
        # Invalid: prefix broader than delegator's
        with pytest.raises(ValueError, match="exceed"):
            validate_delegated_scope(
                DelegationScope(frozenset({"files.read"}), "team"), delegator
            )
        # Invalid: prefix outside delegator's tree
        with pytest.raises(ValueError, match="exceed"):
            validate_delegated_scope(
                DelegationScope(frozenset({"files.read"}), "other"), delegator
            )

    def test_self_grant_is_rejected(self) -> None:
        from s3mp.authorization.domain.delegation import validate_direct_grant
        pid = uuid4()
        future = _now() + timedelta(days=30)
        with pytest.raises(ValueError, match="itself"):
            validate_direct_grant(
                actor_principal_id=pid, target_principal_id=pid,
                permission="files.read", reason="test", expires_at=future,
            )

    def test_key_scope_vs_directory_intersection(self) -> None:
        """Key scope allows upload but directory policy denies → denied."""
        # Key scope: upload allowed
        # Directory policy: no write permission on target prefix
        bindings = [
            Binding(uuid4(), "files.read", Decision.ALLOW, "team", _now(), _now() + timedelta(hours=1), "key"),
        ]
        # Key has upload scope but no write binding → denied
        decision = evaluate("files.write", bindings, object_key="team/data.csv", now=_now())
        assert decision.decision == Decision.DENY

    def test_revoked_key_cannot_presign(self) -> None:
        """Disabled subject cannot receive new presigned URLs."""
        svc = FileService(
            None, _adapter(), "bucket",  # type: ignore[arg-type]
            subject_is_active=lambda _pid: False,
        )
        session = UploadSession(
            uuid4(), uuid4(), uuid4(), uuid4(), "team/file.txt", 100, "text/plain",
            datetime.now(UTC) + timedelta(hours=1),
        )
        with pytest.raises(FileValidationError, match="disabled principal"):
            svc.presign_put(session)


class TestFailureScenarios:
    """Failure drills: quota exceeded, connection down, partial failure."""

    def test_quota_exceeded_isolates_object(self) -> None:
        from s3mp.governance.domain.quota import Quota, QuotaExceededError, QuotaService

        svc = QuotaService()
        quota = Quota(uuid4(), uuid4(), uuid4(), 1000, used_bytes=900, reserved_bytes=0)
        # Reserve 50 → ok
        quota, reservation = svc.reserve(quota, 50)
        assert quota.reserved_bytes == 50
        # Reserve 60 → exceeds limit (900 + 50 + 60 = 1010 > 1000)
        with pytest.raises(QuotaExceededError):
            svc.reserve(quota, 60)
        # Release reservation
        quota, _ = svc.release(quota, reservation)
        assert quota.reserved_bytes == 0

    def test_actual_size_exceeds_declaration(self) -> None:
        from s3mp.governance.domain.quota import Quota, QuotaExceededError, QuotaService

        svc = QuotaService()
        quota = Quota(uuid4(), uuid4(), uuid4(), 1000, used_bytes=0)
        quota, reservation = svc.reserve(quota, 100)
        # Actual size 500 exceeds declared 100 and quota limit (0 + 500 = 500 < 1000 though)
        # But if actual would push over limit...
        quota2 = Quota(uuid4(), uuid4(), uuid4(), 1000, used_bytes=900)
        q2, r2 = svc.reserve(quota2, 50)
        with pytest.raises(QuotaExceededError):
            svc.settle(q2, r2, 150)  # 900 + 150 = 1050 > 1000

    def test_connection_failure_fast_fail(self) -> None:
        """Missing endpoint or region must fail fast, not fall back to defaults."""
        with pytest.raises(ValueError, match="endpoint and region"):
            S3ConnectionConfig(endpoint="https://", region=" ", path_style=True)

    def test_copy_verify_then_delete_source(self) -> None:
        """Move: copy succeeds, delete source fails → PARTIAL_FAILURE."""
        delete_fails: bool = True

        class FailingDeleteStore:
            async def create_multipart(self, key: str, content_type: str) -> str:
                return "upload-1"
            async def upload_part(self, upload_id: str, number: int, body: bytes):
                return None
            async def list_parts(self, upload_id: str):
                return []
            async def complete_multipart(self, upload_id: str, parts):
                return ObjectMetadata("key", 100, "text/plain")
            async def abort_multipart(self, upload_id: str) -> None:
                pass
            async def copy(self, source_key: str, destination_key: str) -> ObjectMetadata:
                return ObjectMetadata(destination_key, 100, "text/plain")
            async def delete(self, key: str) -> None:
                if delete_fails:
                    raise RuntimeError("delete failed")

        svc = MultipartService(FailingDeleteStore())

        async def run():
            op = ObjectOperation(uuid4(), uuid4(), uuid4(), "move", "src/a.txt", "dst/a.txt")
            result = await svc.move(op)
            assert result.status is OperationStatus.PARTIAL_FAILURE
            assert "delete failed" in (result.failure_reason or "")

        import asyncio
        asyncio.run(run())

    def test_batch_delete_requires_exact_confirmation(self) -> None:
        """Batch delete must confirm the exact set of keys."""
        svc = MultipartService(None)  # type: ignore[arg-type]
        op_id = uuid4()

        async def run():
            with pytest.raises(FileValidationError, match="confirmation"):
                await svc.delete_batch(["a.txt", "b.txt"], ["a.txt"], op_id, tenant_id=uuid4(), principal_id=uuid4())

        import asyncio
        asyncio.run(run())


class TestAuditTrailIntegrity:
    """Audit events for security-sensitive operations."""

    def test_audit_event_strips_credentials(self) -> None:
        from s3mp.audit.domain.events import AuditWriter
        writer = AuditWriter()
        event = writer.create(
            uuid4(), "api_key.create", "api_key",
            actor_principal_id=uuid4(),
            resource_id="key-1",
            details={"secret": "sk-abc", "key_id": "k-1", "scope": "files.read"},
        )
        assert "secret" not in event.details
        assert event.details["key_id"] == "k-1"
        assert event.details["scope"] == "files.read"

    def test_audit_event_fingerprint_is_one_way(self) -> None:
        from s3mp.audit.domain.events import AuditWriter
        fp = AuditWriter.fingerprint("presigned-url-content")
        assert len(fp) == 64
        # Cannot reverse
        assert "presigned" not in fp