"""Shared If-Match validation and ETag response handling for mutable resources."""

from s3mp.common.errors import ApiError


def require_if_match(etag: str | None) -> str:
    """Validate the If-Match header; returns the opaque etag value."""
    if not etag:
        raise ApiError(
            "etag_required",
            "If-Match header is required for this operation",
            status_code=428,
        )
    return etag


def check_etag(current: str, expected: str) -> None:
    """Raise ETag mismatch if the resource has changed."""
    if current != expected:
        raise ApiError(
            "etag_mismatch",
            "The resource has been modified; fetch the latest version and retry",
            status_code=412,
        )


def etag_value(resource_id: str, updated_at: str) -> str:
    """Produce a simple opaque ETag from resource identity and timestamp."""
    import hashlib

    return hashlib.sha256(f"{resource_id}:{updated_at}".encode()).hexdigest()[:16]
