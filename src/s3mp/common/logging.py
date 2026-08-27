"""Correlated structured runtime logging with sensitive-value redaction."""

import json
import logging
import re
from collections.abc import Callable, Coroutine, Mapping
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from functools import wraps
from inspect import iscoroutinefunction
from time import perf_counter
from typing import Any, ParamSpec, TypeVar

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
        "signed_url",
        "presigned_url",
        "metadata",
        "body",
    }
)
REDACTED = "[REDACTED]"
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
HEADER_PATTERN = re.compile(
    r"(?i)\b(authorization|x-api-key|api[_-]?key|password|secret|token)\s*[:=]\s*([^\s,;]+)"
)
URL_PASSWORD_PATTERN = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+@", re.I)

CONTEXT_FIELDS = frozenset(
    {
        "request_id",
        "operation_id",
        "tenant_id",
        "application_id",
        "principal_id",
        "resource_type",
        "resource_id",
        "auth_mode",
    }
)
EVENT_FIELDS = frozenset(
    {
        "event",
        "layer",
        "request_id",
        "operation_id",
        "tenant_id",
        "application_id",
        "principal_id",
        "resource_type",
        "resource_id",
        "auth_mode",
        "dependency",
        "dependency_operation",
        "duration_ms",
        "outcome",
        "error_code",
        "error_type",
        "attempt",
        "method",
        "operation",
        "status_code",
        "count",
    }
)
_LOG_CONTEXT: ContextVar[dict[str, object] | None] = ContextVar("runtime_log_context", default=None)
_STANDARD_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__)
_DEFAULT_SLOW_OPERATION_MS = 500
P = ParamSpec("P")
T = TypeVar("T")


def redact_string(value: str) -> str:
    value = BEARER_PATTERN.sub(f"Bearer {REDACTED}", value)
    value = HEADER_PATTERN.sub(lambda match: f"{match.group(1)}={REDACTED}", value)
    return URL_PASSWORD_PATTERN.sub(rf"\g<scheme>{REDACTED}@", value)


def redact(value: Any, key: str | None = None) -> Any:
    """Recursively redact credentials and payload-like values before output."""
    if key is not None and any(part in key.lower() for part in SENSITIVE_KEYS):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(item_key): redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list | tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_string(value)
    return value


def bind_log_context(**fields: object) -> Token[dict[str, object] | None]:
    """Bind approved correlation fields for the current async execution context."""
    unknown = set(fields) - CONTEXT_FIELDS
    if unknown:
        raise ValueError(f"unsupported runtime log context fields: {sorted(unknown)}")
    context = (_LOG_CONTEXT.get() or {}).copy()
    context.update({key: value for key, value in fields.items() if value is not None})
    return _LOG_CONTEXT.set(context)


def reset_log_context(token: Token[dict[str, object] | None]) -> None:
    _LOG_CONTEXT.reset(token)


def current_log_context() -> dict[str, object]:
    return (_LOG_CONTEXT.get() or {}).copy()


def log_event(
    logger: logging.Logger, level: int, event: str, *, layer: str, **fields: object
) -> None:
    """Emit a stable runtime event using only approved structured fields."""
    unknown = set(fields) - EVENT_FIELDS
    if unknown:
        raise ValueError(f"unsupported runtime log event fields: {sorted(unknown)}")
    extra = current_log_context()
    extra.update({"event": event, "layer": layer})
    extra.update({key: value for key, value in fields.items() if value is not None})
    logger.log(level, event, extra=extra)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in current_log_context().items():
            if key not in record.__dict__:
                record.__dict__[key] = value
        record.msg = redact(record.msg)
        if record.args:
            record.args = (
                redact(record.args)
                if isinstance(record.args, Mapping)
                else tuple(redact(item) for item in record.args)
            )
        for key, value in tuple(record.__dict__.items()):
            if key not in _STANDARD_RECORD_FIELDS:
                record.__dict__[key] = redact(value, key)
        return True


class JsonFormatter(logging.Formatter):
    """One safe JSON object per runtime record for container log collectors."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "layer": getattr(record, "layer", "runtime"),
        }
        for field in EVENT_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), ensure_ascii=False, default=str, separators=(",", ":"))


class TextFormatter(logging.Formatter):
    """Compact local formatter that still includes correlation fields."""

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        context = " ".join(
            f"{name}={getattr(record, name)}"
            for name in ("request_id", "operation_id", "tenant_id", "application_id")
            if getattr(record, name, None) is not None
        )
        return f"{rendered} {context}".rstrip()


def configure_logging(
    level: str = "INFO", log_format: str = "json", slow_operation_ms: int = 500
) -> None:
    global _DEFAULT_SLOW_OPERATION_MS
    _DEFAULT_SLOW_OPERATION_MS = slow_operation_ms
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(
        TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        if log_format == "text"
        else JsonFormatter()
    )
    logging.basicConfig(level=level.upper(), handlers=[handler], force=True)


def instrument_dependency(
    dependency: str, operation: str
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]:
    """Record adapter/repository diagnostics without exposing call arguments."""

    def decorator(
        fn: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        logger = logging.getLogger(fn.__module__)

        @wraps(fn)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            started_at = perf_counter()
            slow_threshold_ms = (
                int(getattr(args[0], "_slow_operation_ms", _DEFAULT_SLOW_OPERATION_MS))
                if args
                else _DEFAULT_SLOW_OPERATION_MS
            )
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    f"{dependency}.{operation}.failed",
                    layer="infrastructure",
                    dependency=dependency,
                    dependency_operation=operation,
                    duration_ms=round((perf_counter() - started_at) * 1000, 2),
                    outcome="failed",
                    error_type=type(exc).__name__,
                )
                raise
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            outcome_name = "slow" if duration_ms >= slow_threshold_ms else "completed"
            event_name = f"{dependency}.{operation}.{outcome_name}"
            log_event(
                logger,
                logging.WARNING if duration_ms >= slow_threshold_ms else logging.DEBUG,
                event_name,
                layer="infrastructure",
                dependency=dependency,
                dependency_operation=operation,
                duration_ms=duration_ms,
                outcome="succeeded",
            )
            return result

        return wrapped

    return decorator


def instrument_async_methods(dependency: str) -> Callable[[type[T]], type[T]]:
    """Wrap public async adapter methods with low-noise dependency diagnostics."""

    def decorate(cls: type[T]) -> type[T]:
        for name, member in tuple(vars(cls).items()):
            if not name.startswith("_") and iscoroutinefunction(member):
                setattr(cls, name, instrument_dependency(dependency, name)(member))
        return cls

    return decorate


def instrument_service_operation(
    event: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]:
    """Emit one application-service outcome without serializing command arguments."""

    def decorator(
        fn: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        logger = logging.getLogger(fn.__module__)

        @wraps(fn)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            started_at = perf_counter()
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                error_code = getattr(exc, "code", None)
                log_event(
                    logger,
                    logging.WARNING if error_code else logging.ERROR,
                    f"{event}.{'rejected' if error_code else 'failed'}",
                    layer="service",
                    duration_ms=round((perf_counter() - started_at) * 1000, 2),
                    outcome="rejected" if error_code else "failed",
                    error_code=str(error_code) if error_code else None,
                    error_type=type(exc).__name__,
                )
                raise
            log_event(
                logger,
                logging.INFO,
                f"{event}.completed",
                layer="service",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
                outcome="succeeded",
            )
            return result

        return wrapped

    return decorator


def instrument_service_mutations(domain: str) -> Callable[[type[T]], type[T]]:
    """Instrument externally meaningful service mutations while leaving reads quiet."""
    prefixes = ("create", "delete", "update", "revoke", "rotate", "grant", "remove", "accept")

    def decorate(cls: type[T]) -> type[T]:
        for name, member in tuple(vars(cls).items()):
            if name.startswith(prefixes) and iscoroutinefunction(member):
                setattr(cls, name, instrument_service_operation(f"{domain}.{name}")(member))
        return cls

    return decorate
