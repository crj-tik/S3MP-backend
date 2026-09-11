"""Application configuration loaded from environment variables."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from s3mp.governance.domain.units import gib_to_bytes


class Settings(BaseSettings):
    """Settings loaded from environment variables or one optional env file."""

    model_config = SettingsConfigDict(
        env_prefix="S3MP_", env_file=None, case_sensitive=False, extra="ignore"
    )

    environment: str = "development"
    log_level: str = "INFO"
    log_format: str = "json"
    log_slow_operation_ms: int = Field(default=500, ge=1, le=300000)
    database_url: SecretStr | None = None
    database_url_file: Path | None = None
    redis_url: SecretStr | None = None
    redis_url_file: Path | None = None
    rabbitmq_url: SecretStr | None = None
    rabbitmq_url_file: Path | None = None
    rabbitmq_prefetch: int = Field(default=10, ge=1, le=500)
    rabbitmq_max_retries: int = Field(default=4, ge=1, le=20)
    rabbitmq_processing_timeout_seconds: int = Field(default=300, ge=30, le=86400)
    knowledge_extraction_enabled: bool = True
    knowledge_worker_prefetch: int = Field(default=2, ge=1, le=100)
    knowledge_max_retries: int = Field(default=3, ge=1, le=3)
    knowledge_processing_timeout_seconds: int = Field(default=1800, ge=60, le=86400)
    knowledge_max_source_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    knowledge_max_extracted_characters: int = Field(default=2_000_000, ge=1)
    knowledge_chunk_characters: int = Field(default=12_000, ge=1000, le=100_000)
    knowledge_llm_provider: str | None = None
    knowledge_llm_model: str | None = None
    knowledge_llm_base_url: str | None = None
    knowledge_llm_api_key: SecretStr | None = None
    knowledge_llm_api_key_file: Path | None = None
    knowledge_llm_timeout_seconds: float = Field(default=120.0, gt=0, le=1800)
    elasticsearch_url: str | None = None
    elasticsearch_url_file: Path | None = None
    elasticsearch_api_key: SecretStr | None = None
    elasticsearch_api_key_file: Path | None = None
    knowledge_elasticsearch_index: str = "s3mp-knowledge-cards-v1"
    s3_endpoint: str | None = None
    s3_region: str = "us-east-1"
    s3_path_style: bool = True
    s3_bucket: str | None = None
    s3_bucket_capacity_gib: int | None = Field(default=None, ge=0)
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    api_key_pepper: SecretStr | None = None
    api_key_pepper_file: Path | None = None
    api_key_pepper_version: int = Field(default=1, ge=1)
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    worker_poll_seconds: float = Field(default=5.0, gt=0, le=300)
    worker_batch_size: int = Field(default=10, ge=1, le=500)
    worker_max_attempts: int = Field(default=5, ge=1, le=100)
    worker_lease_seconds: int = Field(default=60, ge=15, le=3600)
    worker_retention_days: int = Field(default=90, ge=1, le=3650)
    api_observability_error_retention_days: int = Field(default=90, ge=1, le=3650)
    browser_origins: tuple[str, ...] = ()
    browser_session_ttl_seconds: int = Field(default=28800, ge=300, le=2592000)
    browser_cookie_secure: bool | None = None
    cas_enabled: bool = False
    cas_login_url: str | None = None
    cas_validate_url: str | None = None
    cas_service_url: str | None = None
    cas_issuer: str | None = None
    cas_session_host: str | None = None
    cas_session_source: str | None = None
    cas_session_signature: SecretStr | None = None
    cas_logout_url: str | None = None
    cas_logout_return_url: str | None = None
    cas_logout_return_parameter: str = "service"
    cas_log_identity_details: bool = False
    cas_log_response_bodies: bool = False
    cas_http_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    cas_state_ttl_seconds: int = Field(default=300, ge=60, le=3600)

    @field_validator("s3_bucket_capacity_gib", mode="before")
    @classmethod
    def empty_bucket_capacity_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"json", "text"}:
            raise ValueError("log_format must be json or text")
        return normalized

    @property
    def s3_bucket_capacity_bytes(self) -> int | None:
        return (
            gib_to_bytes(self.s3_bucket_capacity_gib)
            if self.s3_bucket_capacity_gib is not None
            else None
        )

    @model_validator(mode="after")
    def validate_required_settings(self) -> Self:
        if self.elasticsearch_url is None and self.elasticsearch_url_file is not None:
            self.elasticsearch_url = self.elasticsearch_url_file.read_text(encoding="utf-8").strip()
        for name in (
            "database_url",
            "redis_url",
            "rabbitmq_url",
            "api_key_pepper",
            "knowledge_llm_api_key",
            "elasticsearch_api_key",
        ):
            file_path = getattr(self, f"{name}_file")
            if getattr(self, name) is None and file_path is not None:
                setattr(self, name, SecretStr(file_path.read_text(encoding="utf-8").strip()))
        required_secrets = ["database_url", "redis_url"]
        if self.environment.lower() == "production":
            required_secrets.append("api_key_pepper")
        if self.s3_endpoint is not None:
            required_secrets.extend(["s3_access_key", "s3_secret_key"])
        if self.environment.lower() == "production":
            for name in required_secrets:
                direct = getattr(self, name)
                if direct is None or not direct.get_secret_value():
                    raise ValueError(f"{name} is required")
        if self.s3_endpoint is not None:
            if self.s3_bucket is None:
                raise ValueError("s3_bucket is required when s3_endpoint is configured")
            if self.environment.lower() == "production" and self.s3_bucket_capacity_gib is None:
                raise ValueError(
                    "production requires s3_bucket_capacity_gib when s3_endpoint is configured"
                )
        # Only the analysis worker needs a complete LLM configuration. Keeping
        # that validation in the worker lets migrations, the API, and the
        # Elasticsearch projection worker run while model credentials are being
        # prepared or rotated.
        if self.knowledge_llm_provider and self.knowledge_llm_provider not in {
            "kimi",
            "deepseek",
            "glm",
        }:
            raise ValueError("knowledge_llm_provider must be kimi, deepseek, or glm")
        if "*" in self.browser_origins:
            raise ValueError("browser_origins must not contain wildcard origins")
        if self.environment.lower() == "production" and self.browser_cookie_secure is False:
            raise ValueError("production browser cookies must be secure")
        if self.cas_enabled:
            required_cas = (
                "cas_login_url",
                "cas_validate_url",
                "cas_service_url",
                "cas_issuer",
                "cas_session_host",
                "cas_session_source",
                "cas_session_signature",
            )
            for name in required_cas:
                value = getattr(self, name)
                if value is None or (isinstance(value, SecretStr) and not value.get_secret_value()):
                    raise ValueError(f"{name} is required when cas_enabled")
        logout_values = (
            self.cas_logout_url,
            self.cas_logout_return_url,
            self.cas_logout_return_parameter,
        )
        if any(logout_values[:2]) and not all(logout_values[:2]):
            raise ValueError("cas_logout_url and cas_logout_return_url must be configured together")
        if any(logout_values[:2]):
            for name, value in (
                ("cas_logout_url", self.cas_logout_url),
                ("cas_logout_return_url", self.cas_logout_return_url),
            ):
                parsed = urlparse(value or "")
                allowed_schemes = (
                    {"https"} if self.environment.lower() == "production" else {"http", "https"}
                )
                if parsed.scheme not in allowed_schemes or not parsed.netloc:
                    requirement = "HTTPS" if self.environment.lower() == "production" else "HTTP(S)"
                    raise ValueError(f"{name} must be an absolute {requirement} URL")
            if not self.cas_logout_return_parameter.strip():
                raise ValueError("cas_logout_return_parameter must not be blank")
        return self

    @property
    def secure_browser_cookies(self) -> bool:
        """Production is always secure; development is opt-in insecure only."""
        if self.environment.lower() != "development":
            return True
        return self.browser_cookie_secure is not False

    def secret_value(self, name: str) -> str | None:
        """Resolve a secret while keeping it redacted in settings representations."""
        direct = getattr(self, name)
        if isinstance(direct, SecretStr):
            return direct.get_secret_value()
        return None


@lru_cache
def get_settings() -> Settings:
    env_file = os.environ.get("S3MP_ENV_FILE")
    return Settings(_env_file=env_file) if env_file else Settings()
