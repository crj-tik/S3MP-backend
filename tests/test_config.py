from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic.types import SecretStr

from s3mp.common.config import Settings


def test_reads_external_secret_file(tmp_path: Path) -> None:
    secret_file = tmp_path / "database-url"
    secret_file.write_text("postgresql+asyncpg://example\n", encoding="utf-8")
    settings = Settings(database_url_file=secret_file)
    assert settings.secret_value("database_url") == "postgresql+asyncpg://example"


def test_rejects_multiple_secret_sources() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=SecretStr("value"), database_url_file=Path("secret"))


def test_production_requires_readable_secret_files(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", database_url=SecretStr("inline"))

    database_url = tmp_path / "database-url"
    redis_url = tmp_path / "redis-url"
    database_url.write_text("postgresql+asyncpg://example", encoding="utf-8")
    redis_url.write_text("redis://example", encoding="utf-8")
    settings = Settings(
        environment="production", database_url_file=database_url, redis_url_file=redis_url
    )
    assert settings.secret_value("redis_url") == "redis://example"
