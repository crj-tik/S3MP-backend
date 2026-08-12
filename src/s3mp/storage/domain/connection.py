"""Validated S3 connection settings and SigV4 request construction."""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse


@dataclass(frozen=True, slots=True)
class S3ConnectionConfig:
    endpoint: str
    region: str
    path_style: bool
    max_presign_ttl_seconds: int = 3600
    tls_required: bool = True

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if parsed.scheme not in ({"https"} if self.tls_required else {"http", "https"}):
            raise ValueError("S3 endpoint must use the required TLS scheme")
        if not parsed.netloc or not self.region.strip():
            raise ValueError("S3 endpoint and region are required")
        if self.max_presign_ttl_seconds < 1 or self.max_presign_ttl_seconds > 3600:
            raise ValueError("presigned TTL exceeds the service limit")


@dataclass(frozen=True, slots=True)
class S3Credentials:
    access_key: str
    secret_key: str


@dataclass(frozen=True, slots=True)
class SignedRequest:
    method: str
    url: str
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class PresignedRequest:
    """A short-lived browser-safe request; secrets remain server side."""

    method: str
    url: str
    expires_at: datetime


class SigV4Signer:
    def __init__(self, credentials: S3Credentials) -> None:
        self._credentials = credentials

    def sign(
        self,
        method: str,
        url: str,
        *,
        region: str,
        payload: bytes = b"",
        now: datetime | None = None,
    ) -> SignedRequest:
        timestamp = (now or datetime.now(UTC)).astimezone(UTC)
        parsed = urlparse(url)
        host = parsed.netloc
        amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
        date = timestamp.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(payload).hexdigest()
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        canonical_headers = "".join(
            f"{key}:{value.strip()}\n" for key, value in sorted(headers.items())
        )
        signed_headers = ";".join(sorted(headers))
        canonical_query = urlencode(sorted([]))
        canonical_request = "\n".join(
            [
                method.upper(),
                parsed.path or "/",
                canonical_query,
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        scope = f"{date}/{region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signing_key = _signing_key(self._credentials.secret_key, date, region, "s3")
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self._credentials.access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return SignedRequest(method.upper(), url, headers)

    def presign(
        self,
        method: str,
        url: str,
        *,
        region: str,
        expires_seconds: int,
        now: datetime | None = None,
    ) -> PresignedRequest:
        if not 1 <= expires_seconds <= 3600:
            raise ValueError("presigned TTL exceeds the service limit")
        timestamp = (now or datetime.now(UTC)).astimezone(UTC)
        parsed = urlparse(url)
        amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
        date = timestamp.strftime("%Y%m%d")
        scope = f"{date}/{region}/s3/aws4_request"
        query = parse_qsl(parsed.query, keep_blank_values=True)
        query.extend(
            [
                ("X-Amz-Algorithm", "AWS4-HMAC-SHA256"),
                ("X-Amz-Credential", f"{self._credentials.access_key}/{scope}"),
                ("X-Amz-Date", amz_date),
                ("X-Amz-Expires", str(expires_seconds)),
                ("X-Amz-SignedHeaders", "host"),
            ]
        )
        canonical_query = urlencode(sorted(query), quote_via=quote, safe="~")
        canonical_request = "\n".join(
            [
                method.upper(),
                parsed.path or "/",
                canonical_query,
                f"host:{parsed.netloc}\n",
                "host",
                "UNSIGNED-PAYLOAD",
            ]
        )
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )
        signing_key = _signing_key(self._credentials.secret_key, date, region, "s3")
        signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
        signed_query = f"{canonical_query}&X-Amz-Signature={signature}"
        return PresignedRequest(
            method.upper(),
            urlunparse(parsed._replace(query=signed_query)),
            timestamp.replace(microsecond=0) + timedelta(seconds=expires_seconds),
        )


class S3Adapter:
    """Build only explicitly authorized, path-style SigV4 requests."""

    def __init__(self, config: S3ConnectionConfig, credentials: S3Credentials) -> None:
        self.config = config
        self._signer = SigV4Signer(credentials)

    def build_request(
        self,
        method: str,
        bucket: str,
        object_key: str = "",
        *,
        payload: bytes = b"",
        now: datetime | None = None,
    ) -> SignedRequest:
        url = path_style_url(self.config, bucket, object_key)
        return self._signer.sign(method, url, region=self.config.region, payload=payload, now=now)

    def presign_request(
        self,
        method: str,
        bucket: str,
        object_key: str,
        *,
        expires_seconds: int,
        now: datetime | None = None,
    ) -> PresignedRequest:
        if expires_seconds > self.config.max_presign_ttl_seconds:
            raise ValueError("presigned TTL exceeds the connection limit")
        return self._signer.presign(
            method,
            path_style_url(self.config, bucket, object_key),
            region=self.config.region,
            expires_seconds=expires_seconds,
            now=now,
        )


def _signing_key(secret: str, date: str, region: str, service: str) -> bytes:
    date_key = hmac.new(("AWS4" + secret).encode(), date.encode(), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
    service_key = hmac.new(region_key, service.encode(), hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def path_style_url(config: S3ConnectionConfig, bucket: str, object_key: str = "") -> str:
    if not bucket or "/" in bucket:
        raise ValueError("bucket must be a single DNS label path component")
    suffix = "/".join(quote(part, safe="~") for part in object_key.split("/")) if object_key else ""
    return f"{config.endpoint.rstrip('/')}/{quote(bucket, safe='~')}/{suffix}".rstrip("/")
