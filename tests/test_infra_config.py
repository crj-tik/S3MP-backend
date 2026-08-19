"""Configuration validation for S3 profiles, secret requirements, and endpoint checks."""

from pathlib import Path

import pytest

from s3mp.common.config import Settings
from s3mp.storage.infrastructure.minio import MinioObjectStorageAdapter


class TestS3ProfileValidation:
    def test_s3_profile_enabled_with_endpoint_and_bucket(self) -> None:
        s = Settings(
            s3_endpoint="http://localhost:9000",
            s3_bucket="s3mp-dev",
            s3_access_key="key",
            s3_secret_key="secret",
            environment="development",
        )
        assert s.s3_endpoint == "http://localhost:9000"
        assert s.s3_bucket == "s3mp-dev"

    def test_bucket_capacity_gib_converts_to_internal_bytes(self) -> None:
        s = Settings(
            s3_endpoint="http://localhost:9000",
            s3_bucket="s3mp-dev",
            s3_access_key="key",
            s3_secret_key="secret",
            s3_bucket_capacity_gib=2,
        )
        assert s.s3_bucket_capacity_bytes == 2 * 1024**3

    def test_production_s3_requires_bucket_capacity_gib(self, tmp_path: Path) -> None:
        for secret_name in ("database_url", "redis_url", "s3_access_key", "s3_secret_key"):
            (tmp_path / secret_name).write_text("configured", encoding="utf-8")
        with pytest.raises(ValueError, match="s3_bucket_capacity_gib"):
            Settings(
                environment="production",
                database_url_file=tmp_path / "database_url",
                redis_url_file=tmp_path / "redis_url",
                s3_endpoint="https://s3.example.test",
                s3_bucket="shared",
                s3_access_key_file=tmp_path / "s3_access_key",
                s3_secret_key_file=tmp_path / "s3_secret_key",
            )

    def test_s3_endpoint_requires_bucket(self) -> None:
        with pytest.raises(ValueError, match="s3_bucket"):
            Settings(
                s3_endpoint="http://localhost:9000",
                s3_access_key="key",
                s3_secret_key="secret",
                environment="development",
            )

    def test_production_requires_secret_file_refs(self) -> None:
        with pytest.raises(ValueError, match="requires"):
            Settings(
                s3_endpoint="https://s3.example.com",
                s3_bucket="prod",
                s3_access_key="key",
                s3_secret_key="secret",
                environment="production",
                database_url="postgresql://localhost/test",
            )

    def test_production_requires_secret_files(self) -> None:
        with pytest.raises(ValueError, match="requires"):
            Settings(
                s3_endpoint="https://s3.example.com",
                s3_bucket="prod",
                s3_access_key="key",
                s3_secret_key="secret",
                environment="production",
                database_url="postgresql://localhost/test",
            )

    def test_s3_disabled_by_default(self) -> None:
        s = Settings()
        assert s.s3_endpoint is None
        assert s.s3_bucket is None

    def test_adapter_preserves_region_and_path_style_for_s3_compatible_targets(self) -> None:
        adapter = MinioObjectStorageAdapter(
            Settings(
                s3_endpoint="http://localhost:9000",
                s3_region="ap-southeast-1",
                s3_path_style=True,
                s3_bucket="shared-bucket",
                s3_access_key="key",
                s3_secret_key="secret",
                environment="development",
            )
        )

        assert adapter._client.meta.region_name == "ap-southeast-1"  # noqa: SLF001
        assert adapter._client.meta.config.s3["addressing_style"] == "path"  # noqa: SLF001


class TestSecretSafety:
    def test_secret_value_not_in_repr(self) -> None:
        s = Settings(
            s3_access_key="secret-key-value",
            s3_secret_key="secret-pass-value",
            s3_endpoint="http://localhost:9000",
            s3_bucket="dev",
            environment="development",
        )
        r = repr(s)
        assert "secret-key-value" not in r
        assert "secret-pass-value" not in r
        assert "SecretStr" in r

    def test_env_file_loads_without_credentials(self) -> None:
        """.env file exists but does not embed raw credentials in source."""
        s = Settings(_env_file="deploy/.env")
        assert s.environment == "development"
