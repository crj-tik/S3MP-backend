import logging

from s3mp.common.logging import REDACTED, RedactingFilter, redact


def test_redacts_nested_sensitive_values() -> None:
    assert redact(
        {"username": "safe", "authorization": "Bearer abc", "nested": {"api_key": "x"}}
    ) == {
        "username": "safe",
        "authorization": REDACTED,
        "nested": {"api_key": REDACTED},
    }


def test_redacts_secrets_embedded_in_strings_and_log_arguments() -> None:
    text = "Bearer abc.def x-api-key: topsecret postgresql://user:password@database/db"
    redacted = redact(text)
    assert "abc.def" not in redacted
    assert "topsecret" not in redacted
    assert ":password@" not in redacted

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "request %s", (text,), None)
    assert RedactingFilter().filter(record)
    rendered = record.getMessage()
    assert "abc.def" not in rendered
    assert "topsecret" not in rendered
    assert ":password@" not in rendered
