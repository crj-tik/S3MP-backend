"""MinIO/S3 adapter used by development and integration environments.

The adapter deliberately exposes only tenant-independent S3 primitives. Tenant
prefixes and authorization remain application-service responsibilities.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]

from s3mp.common.config import Settings


class ObjectStorageUnavailable(RuntimeError):
    """Configured object storage could not be contacted or authorized."""


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
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(s3={"addressing_style": "path" if settings.s3_path_style else "virtual"}),
        )

    async def readiness_probe(self) -> None:
        """Validate bucket visibility without creating or deleting any object."""
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("configured S3 bucket is unavailable") from exc

    async def head(self, key: str) -> ObjectMetadata | None:
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.head_object, Bucket=self._bucket, Key=key
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise ObjectStorageUnavailable("S3 object lookup failed") from exc
        return ObjectMetadata(
            key=key,
            content_length=int(response["ContentLength"]),
            etag=str(response.get("ETag", "")).strip('"') or None,
            content_type=response.get("ContentType"),
            version_id=response.get("VersionId"),
            checksum_sha256=response.get("ChecksumSHA256"),
        )

    async def put(self, key: str, body: bytes, content_type: str) -> ObjectMetadata:
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 object upload failed") from exc
        result = await self.head(key)
        if result is None:
            raise ObjectStorageUnavailable("uploaded object could not be verified")
        return result

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 object delete failed") from exc

    async def copy(self, source_key: str, destination_key: str) -> ObjectMetadata:
        try:
            await asyncio.to_thread(
                self._client.copy_object,
                Bucket=self._bucket,
                Key=destination_key,
                CopySource={"Bucket": self._bucket, "Key": source_key},
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 object copy failed") from exc
        result = await self.head(destination_key)
        if result is None:
            raise ObjectStorageUnavailable("copied object could not be verified")
        return result

    async def presign_get(self, key: str, expires_in: int) -> str:
        try:
            return await asyncio.to_thread(
                self._client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 signing failed") from exc

    # ── Multipart ──────────────────────────────────────────────────────────

    async def create_multipart_upload(self, key: str, content_type: str) -> str:
        """Initiate a provider-side multipart upload; returns the provider upload ID."""
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.create_multipart_upload,
                Bucket=self._bucket,
                Key=key,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 multipart create failed") from exc
        upload_id = response.get("UploadId")
        if not upload_id:
            raise ObjectStorageUnavailable("S3 multipart create returned no UploadId")
        return upload_id

    async def upload_part(
        self, key: str, upload_id: str, part_number: int, body: bytes
    ) -> dict[str, object]:
        """Upload a single part; returns {'etag': str, 'part_number': int}."""
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.upload_part,
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
                PartNumber=part_number,
                Body=body,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 part upload failed") from exc
        etag = str(response.get("ETag", "")).strip('"')
        return {"etag": etag, "part_number": part_number}

    async def complete_multipart_upload(
        self, key: str, upload_id: str, parts: list[dict[str, object]]
    ) -> ObjectMetadata:
        """Complete the multipart upload with the provider; returns final ObjectMetadata."""
        try:
            multipart_upload: dict[str, Any] = {"Parts": [
                {"ETag": str(p["etag"]), "PartNumber": int(p["part_number"])}
                for p in parts
            ]}
            await asyncio.to_thread(
                self._client.complete_multipart_upload,
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload=multipart_upload,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageUnavailable("S3 multipart complete failed") from exc
        result = await self.head(key)
        if result is None:
            raise ObjectStorageUnavailable("completed multipart object could not be verified")
        return result

    async def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        """Abort a provider-side multipart upload best-effort."""
        try:
            await asyncio.to_thread(
                self._client.abort_multipart_upload,
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchUpload", "404", "NotFound"}:
                return  # already cleaned up — not an error
            raise ObjectStorageUnavailable("S3 multipart abort failed") from exc

    async def list_parts(self, key: str, upload_id: str) -> list[dict[str, object]]:
        """List uploaded parts for a provider-side multipart session."""
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                self._client.list_parts,
                Bucket=self._bucket,
                Key=key,
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
