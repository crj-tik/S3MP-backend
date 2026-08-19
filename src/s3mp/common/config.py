"""Application configuration and external secret references."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from s3mp.governance.domain.units import gib_to_bytes


class Settings(BaseSettings):
    """Settings loaded from environment; secrets may be referenced by files."""

    model_config = SettingsConfigDict(
        env_prefix="S3MP_", env_file=None, case_sensitive=False, extra="ignore"
    )

    environment: str = "development"
    log_level: str = "INFO"
    database_url: SecretStr | None = None
    database_url_file: Path | None = None
    redis_url: SecretStr | None = None
    redis_url_file: Path | None = None
    s3_endpoint: str | None = None
    s3_region: str = "us-east-1"
    s3_path_style: bool = True
    s3_bucket: str | None = None
    s3_bucket_capacity_gib: int | None = Field(default=None, ge=0)
    s3_access_key: SecretStr | None = None
    s3_access_key_file: Path | None = None
    s3_secret_key: SecretStr | None = None
    s3_secret_key_file: Path | None = None
    api_key_pepper: SecretStr | None = None
    api_key_pepper_file: Path | None = None
    api_key_pepper_version: int = Field(default=1, ge=1)
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    worker_poll_seconds: float = Field(default=5.0, gt=0, le=300)
    worker_batch_size: int = Field(default=10, ge=1, le=500)
    worker_max_attempts: int = Field(default=5, ge=1, le=100)
    worker_lease_seconds: int = Field(default=60, ge=15, le=3600)
    worker_retention_days: int = Field(default=30, ge=1, le=3650)
    browser_origins: tuple[str, ...] = ()
    browser_session_ttl_seconds: int = Field(default=28800, ge=300, le=2592000)
    browser_cookie_secure: bool | None = None

    @field_validator("s3_bucket_capacity_gib", mode="before")
    @classmethod
    def empty_bucket_capacity_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def s3_bucket_capacity_bytes(self) -> int | None:
        return (
            gib_to_bytes(self.s3_bucket_capacity_gib)
            if self.s3_bucket_capacity_gib is not None
            else None
        )

    @model_validator(mode="after")
    def validate_secret_sources(self) -> Self:
        required_secrets = ["database_url", "redis_url"]
        if self.s3_endpoint is not None:
            required_secrets.extend(["s3_access_key", "s3_secret_key"])
        for name in required_secrets:
            direct = getattr(self, name)
            reference = getattr(self, f"{name}_file")
            if direct is not None and reference is not None:
                raise ValueError(f"set only one of {name} and {name}_file")
            if self.environment.lower() == "production":
                if direct is not None or reference is None:
                    raise ValueError(f"production requires {name}_file instead of {name}")
                if not reference.is_file() or not reference.read_text(encoding="utf-8").strip():
                    raise ValueError(f"{name}_file must reference a readable non-empty file")
        if self.s3_endpoint is not None:
            if self.s3_bucket is None:
                raise ValueError("s3_bucket is required when s3_endpoint is configured")
            if self.environment.lower() == "production" and self.s3_bucket_capacity_gib is None:
                raise ValueError(
                    "production requires s3_bucket_capacity_gib when s3_endpoint is configured"
                )
        if "*" in self.browser_origins:
            raise ValueError("browser_origins must not contain wildcard origins")
        if self.environment.lower() == "production" and self.browser_cookie_secure is False:
            raise ValueError("production browser cookies must be secure")
        return self

    @property
    def secure_browser_cookies(self) -> bool:
        """Production is always secure; development is opt-in insecure only."""
        if self.environment.lower() != "development":
            return True
        return self.browser_cookie_secure is not False

    def secret_value(self, name: str) -> str | None:
        """Resolve a secret from its environment value or mounted file reference."""
        direct = getattr(self, name)
        if isinstance(direct, SecretStr):
            return direct.get_secret_value()
        reference = getattr(self, f"{name}_file")
        if isinstance(reference, Path):
            return reference.read_text(encoding="utf-8").strip()
        return None


@lru_cache
def get_settings() -> Settings:
    env_file = os.environ.get("S3MP_ENV_FILE")
    return Settings(_env_file=env_file) if env_file else Settings()
