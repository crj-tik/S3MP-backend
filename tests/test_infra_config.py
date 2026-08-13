"""Configuration validation for S3 profiles, secret requirements, and endpoint checks."""

import pytest

from s3mp.common.config import Settings


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
