from datetime import UTC, datetime

import pytest

from s3mp.storage.domain.connection import (
    S3Adapter,
    S3ConnectionConfig,
    S3Credentials,
    path_style_url,
)


def test_s3_connection_requires_explicit_tls_region_and_ttl() -> None:
    config = S3ConnectionConfig("https://s3.example.test", "cn-test-1", True)
    assert path_style_url(config, "bucket", "team/report.csv") == (
        "https://s3.example.test/bucket/team/report.csv"
    )
    with pytest.raises(ValueError):
        S3ConnectionConfig("http://s3.example.test", "region", True)
    with pytest.raises(ValueError):
        S3ConnectionConfig("https://s3.example.test", "region", True, max_presign_ttl_seconds=3601)


def test_sigv4_request_is_explicit_and_signed() -> None:
    adapter = S3Adapter(
        S3ConnectionConfig("https://s3.example.test", "cn-test-1", True),
        S3Credentials("AKIA_TEST", "secret"),
    )
    request = adapter.build_request(
        "GET",
        "bucket",
        "object.txt",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert request.method == "GET"
    assert request.headers["x-amz-content-sha256"]
    assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256")
