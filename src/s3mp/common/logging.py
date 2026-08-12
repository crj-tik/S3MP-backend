"""Structured logging with sensitive value redaction."""

import logging
import re
from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "password",
        "secret",
        "token",
        "api_key",
        "x-api-key",
        "access_key",
    }
)
REDACTED = "[REDACTED]"
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
HEADER_PATTERN = re.compile(
    r"(?i)\b(authorization|x-api-key|api[_-]?key|password|secret|token)\s*[:=]\s*([^\s,;]+)"
)
URL_PASSWORD_PATTERN = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+@", re.I)


def redact_string(value: str) -> str:
    value = BEARER_PATTERN.sub(f"Bearer {REDACTED}", value)
    value = HEADER_PATTERN.sub(lambda match: f"{match.group(1)}={REDACTED}", value)
    return URL_PASSWORD_PATTERN.sub(rf"\g<scheme>{REDACTED}@", value)


def redact(value: Any, key: str | None = None) -> Any:
    """Recursively redact values whose keys or contents indicate credentials."""
    if key is not None and any(part in key.lower() for part in SENSITIVE_KEYS):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(item_key): redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_string(value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = redact(record.args)
            else:
                record.args = tuple(redact(item) for item in record.args)
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
