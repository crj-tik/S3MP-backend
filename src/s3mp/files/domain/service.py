"""Authorized file access, upload sessions, and opaque cursors."""

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from s3mp.storage.domain.connection import PresignedRequest, S3Adapter
from s3mp.storage.domain.policy import canonical_object_key


class FileValidationError(ValueError):
    code = "file_validation_failed"


class FileConflictError(FileValidationError):
    code = "file_already_exists"


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    key: str
    content_length: int
    content_type: str
    etag: str | None = None
    checksum: str | None = None


@dataclass(frozen=True, slots=True)
class UploadSession:
    id: UUID
    tenant_id: UUID
    principal_id: UUID
    storage_space_id: UUID
    object_key: str
    declared_length: int
    content_type: str
    expires_at: datetime
    checksum: str | None = None
    status: str = "pending"


class FileStore(Protocol):
    async def list(self, prefix: str) -> list[ObjectMetadata]: ...

    async def head(self, key: str) -> ObjectMetadata | None: ...

    async def put(self, key: str, body: bytes, content_type: str) -> ObjectMetadata: ...


class QuotaLedger(Protocol):
    """Minimal reservation seam; the durable quota model arrives in change 9.1."""

    async def reserve(self, byte_count: int) -> object: ...

    async def release(self, reservation: object) -> None: ...


class SecureCursorCodec:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 16:
            raise ValueError("cursor secret must be at least 16 bytes")
        self._secret = secret

    def encode(self, tenant_id: UUID, principal_id: UUID, position: str, prefix: str) -> str:
        payload = json.dumps(
            {"t": str(tenant_id), "p": str(principal_id), "o": position, "x": prefix},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")

    def decode(self, token: str, tenant_id: UUID, principal_id: UUID, prefix: str) -> str:
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            payload, signature = raw[:-32], raw[-32:]
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            decoded = json.loads(payload)
            if (
                decoded["t"] != str(tenant_id)
                or decoded["p"] != str(principal_id)
                or decoded["x"] != prefix
            ):
                raise ValueError
            return str(decoded["o"])
        except (KeyError, ValueError, json.JSONDecodeError) as error:
            raise FileValidationError("invalid cursor") from error


class FileService:
    def __init__(
        self,
        store: FileStore,
        adapter: S3Adapter,
        bucket: str,
        max_presign_ttl: int = 900,
        quota: QuotaLedger | None = None,
        subject_is_active: Callable[[UUID], bool] | None = None,
    ) -> None:
        self._store, self._adapter, self._bucket = store, adapter, bucket
        self._max_presign_ttl = min(max_presign_ttl, adapter.config.max_presign_ttl_seconds)
        self._quota = quota
        self._subject_is_active = subject_is_active or (lambda _principal_id: True)

    async def list_authorized(self, prefix: str) -> list[ObjectMetadata]:
        canonical_object_key(prefix, allow_empty=True)
        objects = await self._store.list(prefix)
        return [item for item in objects if _within_prefix(item.key, prefix)]

    async def head_authorized(self, key: str, prefix: str) -> ObjectMetadata | None:
        self._authorize_key(key, prefix)
        return await self._store.head(key)

    def create_upload_session(
        self,
        tenant_id: UUID,
        principal_id: UUID,
        space_id: UUID,
        key: str,
        prefix: str,
        length: int,
        content_type: str,
        *,
        checksum: str | None = None,
        ttl_seconds: int | None = None,
    ) -> UploadSession:
        if not self._subject_is_active(principal_id):
            raise FileValidationError("disabled principal cannot create upload sessions")
        self._authorize_key(key, prefix)
        if length < 0 or not content_type:
            raise FileValidationError("upload metadata is invalid")
        expiry = datetime.now(UTC) + timedelta(seconds=self._ttl(ttl_seconds))
        return UploadSession(
            uuid4(), tenant_id, principal_id, space_id, key, length, content_type, expiry, checksum
        )

    def presign_put(
        self, session: UploadSession, *, ttl_seconds: int | None = None
    ) -> PresignedRequest:
        self._pending(session)
        if not self._subject_is_active(session.principal_id):
            raise FileValidationError("disabled principal cannot receive a new signature")
        return self._adapter.presign_request(
            "PUT", self._bucket, session.object_key, expires_seconds=self._ttl(ttl_seconds)
        )

    async def complete_upload(self, session: UploadSession) -> tuple[UploadSession, ObjectMetadata]:
        self._pending(session)
        object_data = await self._store.head(session.object_key)
        if object_data is None or object_data.content_length != session.declared_length:
            raise FileValidationError("uploaded object metadata does not match session")
        if object_data.content_type != session.content_type:
            raise FileValidationError("uploaded Content-Type does not match session")
        if session.checksum and object_data.checksum != session.checksum:
            raise FileValidationError("uploaded checksum does not match session")
        return replace(session, status="completed"), object_data

    def presign_get(
        self, key: str, prefix: str, *, ttl_seconds: int | None = None
    ) -> tuple[PresignedRequest, str]:
        self._authorize_key(key, prefix)
        request = self._adapter.presign_request(
            "GET", self._bucket, key, expires_seconds=self._ttl(ttl_seconds)
        )
        return request, hashlib.sha256(request.url.encode()).hexdigest()

    def _ttl(self, requested: int | None) -> int:
        if requested is None:
            return self._max_presign_ttl
        if not 1 <= requested <= self._max_presign_ttl:
            raise FileValidationError("presigned TTL exceeds the service limit")
        return requested

    def _authorize_key(self, key: str, prefix: str) -> None:
        canonical_object_key(key)
        canonical_object_key(prefix, allow_empty=True)
        if not _within_prefix(key, prefix):
            raise FileValidationError("object key falls outside authorized prefix")

    @staticmethod
    def _pending(session: UploadSession) -> None:
        if session.status != "pending" or session.expires_at <= datetime.now(UTC):
            raise FileValidationError("upload session is not pending")


def _within_prefix(key: str, prefix: str) -> bool:
    return not prefix or key == prefix or key.startswith(f"{prefix}/")
