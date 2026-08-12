"""Storage operation policy, canonical key checks, and safe probes."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from s3mp.authorization.domain.evaluator import validate_canonical_prefix
from s3mp.storage.domain.connection import S3Adapter, SignedRequest


class StorageOperation(StrEnum):
    LIST = "LIST"
    HEAD = "HEAD"
    GET = "GET"
    PUT = "PUT"
    DELETE = "DELETE"


class StoragePolicyError(ValueError):
    code = "storage_policy_denied"


class StorageUnsupportedError(StoragePolicyError):
    code = "storage_operation_unsupported"


@dataclass(frozen=True, slots=True)
class StorageCapabilities:
    list_objects: bool = True
    head_object: bool = True
    proxy_upload: bool = True
    presigned_get: bool = True
    presigned_put: bool = True
    multipart: bool = False
    copy_object: bool = False
    delete_object: bool = False

    def supports(self, operation: StorageOperation) -> bool:
        return {
            StorageOperation.LIST: self.list_objects,
            StorageOperation.HEAD: self.head_object,
            StorageOperation.GET: self.presigned_get,
            StorageOperation.PUT: self.proxy_upload or self.presigned_put,
            StorageOperation.DELETE: self.delete_object,
        }[operation]


def choose_upload_mode(capabilities: StorageCapabilities, *, direct_requested: bool) -> str:
    """Select direct upload only when it is explicitly supported, otherwise proxy."""
    if direct_requested and capabilities.presigned_put:
        return "direct"
    if capabilities.proxy_upload:
        return "proxy"
    raise StorageUnsupportedError("connection supports neither direct nor proxy upload")


def canonical_object_key(key: str, *, allow_empty: bool = False) -> str:
    if not isinstance(key, str) or (not key and not allow_empty):
        raise StoragePolicyError("object key is required")
    try:
        validate_canonical_prefix(key)
    except ValueError as error:
        raise StoragePolicyError("object key is not canonical") from error
    return key


@dataclass(frozen=True, slots=True)
class AuthorizedCommand:
    tenant_id: UUID
    storage_space_id: UUID
    operation: StorageOperation
    bucket: str
    object_key: str = ""

    def __post_init__(self) -> None:
        if not self.bucket:
            raise StoragePolicyError("bucket is required")
        canonical_object_key(self.object_key, allow_empty=self.operation is StorageOperation.LIST)


def build_authorized_request(
    adapter: S3Adapter, command: AuthorizedCommand, capabilities: StorageCapabilities
) -> SignedRequest:
    if not capabilities.supports(command.operation):
        raise StorageUnsupportedError(f"{command.operation} is disabled for this connection")
    method = {
        StorageOperation.LIST: "GET",
        StorageOperation.HEAD: "HEAD",
        StorageOperation.GET: "GET",
        StorageOperation.PUT: "PUT",
        StorageOperation.DELETE: "DELETE",
    }[command.operation]
    return adapter.build_request(method, command.bucket, command.object_key)


class ProbeClient(Protocol):
    async def head(self, bucket: str, key: str) -> object: ...

    async def put(self, bucket: str, key: str, body: bytes, content_type: str) -> object: ...

    async def get(self, bucket: str, key: str) -> bytes: ...

    async def delete(self, bucket: str, key: str) -> object: ...


async def read_probe(client: ProbeClient, bucket: str, key: str = "") -> bool:
    """Only issue a non-mutating head request; callers may use a known sentinel key."""
    try:
        await client.head(bucket, canonical_object_key(key, allow_empty=True))
    except Exception:  # A missing sentinel and unreachable connection are both non-acceptance.
        return False
    return True


async def acceptance_prefix_round_trip(client: ProbeClient, bucket: str, test_key: str) -> bool:
    """The only destructive probe, scoped to a caller-owned test prefix."""
    key = canonical_object_key(test_key)
    marker = b"s3mp-storage-probe"
    try:
        await client.put(bucket, key, marker, "application/octet-stream")
        if await client.get(bucket, key) != marker:
            return False
    except Exception:
        return False
    finally:
        try:
            await client.delete(bucket, key)
        except Exception:  # noqa: S110 - cleanup failure must not mask probe result
            return False
    return True
