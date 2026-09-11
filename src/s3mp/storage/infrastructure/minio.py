"""MinIO/S3 adapter used by development and integration environments.

The adapter deliberately exposes only tenant-independent S3 primitives. Tenant
prefixes and authorization remain application-service responsibilities.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any, cast

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from s3mp.common.config import Settings
from s3mp.common.logging import instrument_dependency, log_event
from s3mp.storage.domain.checksum import provider_checksum_to_hex
from s3mp.storage.domain.policy import ProviderTarget


class ObjectStorageUnavailable(RuntimeError):
    """Configured object storage could not be contacted or authorized."""


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObjectMetadata:
    key: str
    content_length: int
    etag: str | None
    content_type: str | None
    version_id: str | None = None
    checksum_sha256: str | None = None


class MinioObjectStorageAdapter:
    """Async facade over the thread-safe boto3 S3 client.

    It is intentionally instantiated only from validated Settings. Credentials
    are read at construction time and never retained in a serializable model.
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.s3_endpoint or not settings.s3_bucket:
            raise ValueError("S3 endpoint and bucket are required for object storage")
        access_key = settings.secret_value("s3_access_key")
        secret_key = settings.secret_value("s3_secret_key")
        if not access_key or not secret_key:
            raise ValueError("S3 access and secret key references are required")
        self._bucket = settings.s3_bucket
        self._slow_operation_ms = settings.log_slow_operation_ms
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(s3={"addressing_style": "path" if settings.s3_path_style else "virtual"}),
        )

    @instrument_dependency("storage", "readiness_probe")
    async def readiness_probe(self) -> None:
        """Validate bucket visibility without creating or deleting any object."""
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("configured S3 bucket is unavailable") from exc

    def _assert_shared_bucket(self, target: ProviderTarget) -> None:
        """Reject stale or forged targets that point outside the platform bucket."""
        if target.bucket != self._bucket:
            raise ObjectStorageUnavailable("provider target does not use the shared S3 bucket")

    @instrument_dependency("storage", "head")
    async def head(self, target: ProviderTarget) -> ObjectMetadata | None:
        self._assert_shared_bucket(target)
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.head_object,
                Bucket=target.bucket,
                Key=target.key,
                ChecksumMode="ENABLED",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise ObjectStorageUnavailable("S3 object lookup failed") from exc
        return ObjectMetadata(
            key=target.key,
            content_length=int(response["ContentLength"]),
            etag=str(response.get("ETag", "")).strip('"') or None,
            content_type=response.get("ContentType"),
            version_id=response.get("VersionId"),
            checksum_sha256=provider_checksum_to_hex(response.get("ChecksumSHA256")),
        )

    @instrument_dependency("storage", "get")
    async def get(self, target: ProviderTarget, *, max_bytes: int) -> bytes | None:
        """Read one object with a server-enforced size limit.

        This is intentionally only used by trusted platform workers. API callers
        continue to receive presigned URLs rather than object content.
        """
        self._assert_shared_bucket(target)
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        metadata = await self.head(target)
        if metadata is None:
            return None
        if metadata.content_length > max_bytes:
            raise ObjectStorageUnavailable("S3 object exceeds configured worker size limit")
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.get_object, Bucket=target.bucket, Key=target.key
            )
            stream = response["Body"]
            try:
                body = await asyncio.to_thread(stream.read, max_bytes + 1)
            finally:
                await asyncio.to_thread(stream.close)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise ObjectStorageUnavailable("S3 object read failed") from exc
        except BotoCoreError as exc:
            raise ObjectStorageUnavailable("S3 object read failed") from exc
        if len(body) > max_bytes:
            raise ObjectStorageUnavailable("S3 object exceeds configured worker size limit")
        return cast(bytes, body)

    @instrument_dependency("storage", "hash_sha256")
    async def hash_sha256(
        self, target: ProviderTarget, *, chunk_size: int = 8 * 1024 * 1024
    ) -> str:
        """Stream an object through SHA-256 without buffering the full body."""
        self._assert_shared_bucket(target)
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.get_object, Bucket=target.bucket, Key=target.key
            )
            stream = response["Body"]
            digest = hashlib.sha256()
            bytes_read = 0
            try:
                while True:
                    chunk = await asyncio.to_thread(stream.read, chunk_size)
                    if not chunk:
                        break
                    digest.update(chunk)
                    bytes_read += len(chunk)
            finally:
                await asyncio.to_thread(stream.close)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                raise ObjectStorageUnavailable("S3 object read failed: object not found") from exc
            raise ObjectStorageUnavailable("S3 object hash read failed") from exc
        except (BotoCoreError, OSError) as exc:
            raise ObjectStorageUnavailable("S3 object hash read failed") from exc
        log_event(
            logger,
            logging.INFO,
            "storage_object_sha256_completed",
            layer="storage",
            count=bytes_read,
            outcome="success",
        )
        return f"sha256:{digest.hexdigest()}"

    @instrument_dependency("storage", "put")
    async def put(self, target: ProviderTarget, body: bytes, content_type: str) -> ObjectMetadata:
        self._assert_shared_bucket(target)
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=target.bucket,
                Key=target.key,
                Body=body,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 object upload failed") from exc
        result = await self.head(target)
        if result is None:
            raise ObjectStorageUnavailable("uploaded object could not be verified")
        return result

    @instrument_dependency("storage", "delete")
    async def delete(self, target: ProviderTarget) -> None:
        self._assert_shared_bucket(target)
        try:
            await asyncio.to_thread(
                self._client.delete_object, Bucket=target.bucket, Key=target.key
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 object delete failed") from exc

    @instrument_dependency("storage", "list_objects")
    async def list_objects(
        self,
        prefix: str = "",
        *,
        continuation_token: str | None = None,
        max_keys: int = 1000,
    ) -> tuple[list[ObjectMetadata], str | None]:
        """List objects only inside the configured shared bucket.

        The caller supplies a server-derived namespace prefix; bucket selection
        and credentials remain owned by this adapter.
        """
        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Prefix": prefix,
            "MaxKeys": max(1, min(max_keys, 1000)),
        }
        if continuation_token:
            params["ContinuationToken"] = continuation_token
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.list_objects_v2, **params
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 object listing failed") from exc
        objects = [
            ObjectMetadata(
                key=str(item["Key"]),
                content_length=int(item.get("Size", 0)),
                etag=str(item.get("ETag", "")).strip('"') or None,
                content_type=None,
                version_id=None,
            )
            for item in response.get("Contents", [])
        ]
        return objects, response.get("NextContinuationToken")

    @instrument_dependency("storage", "copy")
    async def copy(self, source: ProviderTarget, destination: ProviderTarget) -> ObjectMetadata:
        self._assert_shared_bucket(source)
        self._assert_shared_bucket(destination)
        try:
            await asyncio.to_thread(
                self._client.copy_object,
                Bucket=destination.bucket,
                Key=destination.key,
                CopySource={"Bucket": source.bucket, "Key": source.key},
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 object copy failed") from exc
        result = await self.head(destination)
        if result is None:
            raise ObjectStorageUnavailable("copied object could not be verified")
        return result

    @instrument_dependency("storage", "presign_get")
    async def presign_get(self, target: ProviderTarget, expires_in: int) -> str:
        self._assert_shared_bucket(target)
        try:
            signed_url = await asyncio.to_thread(
                self._client.generate_presigned_url,
                "get_object",
                Params={"Bucket": target.bucket, "Key": target.key},
                ExpiresIn=expires_in,
            )
            return cast(str, signed_url)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 signing failed") from exc

    @instrument_dependency("storage", "presign_put")
    async def presign_put(
        self,
        target: ProviderTarget,
        content_type: str,
        expires_in: int,
        checksum_sha256: str | None = None,
    ) -> str:
        """Create a short-lived PUT URL for one server-derived object target."""
        self._assert_shared_bucket(target)
        if not content_type or content_type.strip() != content_type:
            raise ValueError("content type is required for a presigned PUT")
        try:
            params: dict[str, str] = {
                "Bucket": target.bucket,
                "Key": target.key,
                "ContentType": content_type,
            }
            if checksum_sha256 is not None:
                params["ChecksumSHA256"] = checksum_sha256
            signed_url = await asyncio.to_thread(
                self._client.generate_presigned_url,
                "put_object",
                Params=params,
                ExpiresIn=expires_in,
            )
            return cast(str, signed_url)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 PUT signing failed") from exc

    # ── Multipart ──────────────────────────────────────────────────────────

    @instrument_dependency("storage", "create_multipart_upload")
    async def create_multipart_upload(
        self, target: ProviderTarget, content_type: str, checksum_sha256: str | None = None
    ) -> str:
        """Initiate a provider-side multipart upload; returns the provider upload ID."""
        self._assert_shared_bucket(target)
        try:
            params: dict[str, Any] = {
                "Bucket": target.bucket,
                "Key": target.key,
                "ContentType": content_type,
            }
            if checksum_sha256 is not None:
                params["ChecksumAlgorithm"] = "SHA256"
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.create_multipart_upload, **params
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 multipart create failed") from exc
        upload_id = response.get("UploadId")
        if not upload_id:
            raise ObjectStorageUnavailable("S3 multipart create returned no UploadId")
        return cast(str, upload_id)

    @instrument_dependency("storage", "upload_part")
    async def upload_part(
        self, target: ProviderTarget, upload_id: str, part_number: int, body: bytes
    ) -> dict[str, object]:
        """Upload a single part; returns {'etag': str, 'part_number': int}."""
        self._assert_shared_bucket(target)
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.upload_part,
                Bucket=target.bucket,
                Key=target.key,
                UploadId=upload_id,
                PartNumber=part_number,
                Body=body,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 part upload failed") from exc
        etag = str(response.get("ETag", "")).strip('"')
        return {"etag": etag, "part_number": part_number}

    @instrument_dependency("storage", "complete_multipart_upload")
    async def complete_multipart_upload(
        self, target: ProviderTarget, upload_id: str, parts: list[dict[str, object]]
    ) -> ObjectMetadata:
        """Complete the multipart upload with the provider; returns final ObjectMetadata."""
        self._assert_shared_bucket(target)
        try:
            multipart_upload: dict[str, Any] = {
                "Parts": [
                    {
                        "ETag": str(p["etag"]),
                        "PartNumber": int(cast(int | str, p["part_number"])),
                    }
                    for p in parts
                ]
            }
            await asyncio.to_thread(
                self._client.complete_multipart_upload,
                Bucket=target.bucket,
                Key=target.key,
                UploadId=upload_id,
                MultipartUpload=multipart_upload,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 multipart complete failed") from exc
        result = await self.head(target)
        if result is None:
            raise ObjectStorageUnavailable("completed multipart object could not be verified")
        return result

    @instrument_dependency("storage", "abort_multipart_upload")
    async def abort_multipart_upload(self, target: ProviderTarget, upload_id: str) -> None:
        """Abort a provider-side multipart upload best-effort."""
        self._assert_shared_bucket(target)
        try:
            await asyncio.to_thread(
                self._client.abort_multipart_upload,
                Bucket=target.bucket,
                Key=target.key,
                UploadId=upload_id,
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchUpload", "404", "NotFound"}:
                return  # already cleaned up — not an error
            raise ObjectStorageUnavailable("S3 multipart abort failed") from exc

    @instrument_dependency("storage", "list_parts")
    async def list_parts(self, target: ProviderTarget, upload_id: str) -> list[dict[str, object]]:
        """List uploaded parts for a provider-side multipart session."""
        self._assert_shared_bucket(target)
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.list_parts,
                Bucket=target.bucket,
                Key=target.key,
                UploadId=upload_id,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 list parts failed") from exc
        parts = response.get("Parts") or []
        return [
            {
                "part_number": p["PartNumber"],
                "etag": str(p.get("ETag", "")).strip('"'),
                "size": p.get("Size", 0),
            }
            for p in parts
        ]
