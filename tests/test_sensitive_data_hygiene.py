"""Verify sensitive data never enters logs, audit, traces, or metrics."""

import hashlib
import json
from uuid import uuid4

from s3mp.audit.domain.events import AuditWriter
from s3mp.common.logging import redact, redact_string


class TestLogRedaction:
    """Sensitive values must never appear in log output."""

    def test_bearer_token_redacted(self) -> None:
        raw = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc123"
        result = redact_string(raw)
        assert "eyJhbGci" not in result
        assert "[REDACTED]" in result

    def test_api_key_header_redacted(self) -> None:
        raw = "x-api-key: sk-proj-abc123secret"
        result = redact_string(raw)
        assert "sk-proj-abc123secret" not in result
        assert "[REDACTED]" in result

    def test_password_in_url_redacted(self) -> None:
        raw = "postgresql://admin:secret123@localhost:5432/db"
        result = redact_string(raw)
        assert "secret123" not in result
        assert "[REDACTED]" in result

    def test_dict_key_redacted(self) -> None:
        payload = {"password": "my-secret", "username": "alice"}
        result = redact(payload)
        assert result["password"] == "[REDACTED]"
        assert result["username"] == "alice"

    def test_nested_dict_key_redacted(self) -> None:
        payload = {"auth": {"token": "abc123", "realm": "users"}}
        result = redact(payload)
        assert result["auth"]["token"] == "[REDACTED]"
        assert result["auth"]["realm"] == "users"

    def test_list_item_redacted(self) -> None:
        payload = ["normal", "Bearer xyz-secret-token"]
        result = redact(payload)
        assert result[0] == "normal"
        assert "xyz-secret-token" not in result[1]
        assert "[REDACTED]" in result[1]

    def test_secret_key_redacted(self) -> None:
        payload = {"api_key": "sk-12345", "name": "my-app"}
        result = redact(payload)
        assert result["api_key"] == "[REDACTED]"
        assert result["name"] == "my-app"

    def test_authorization_header_redacted(self) -> None:
        payload = {"authorization": "Bearer token-value", "data": "safe"}
        result = redact(payload)
        assert result["authorization"] == "[REDACTED]"
        assert result["data"] == "safe"


class TestAuditEventNoSensitiveData:
    """Audit events must never contain credentials, secrets, or full URLs."""

    def test_url_field_stripped(self) -> None:
        writer = AuditWriter()
        event = writer.create(
            uuid4(), "file.download", "file_object",
            details={"url": "https://s3.example.com/bucket/key?SigV4=...", "user": "alice"},
        )
        assert "url" not in event.details
        assert event.details.get("user") == "alice"

    def test_secret_field_stripped(self) -> None:
        writer = AuditWriter()
        event = writer.create(
            uuid4(), "api_key.create", "api_key",
            details={"secret": "sk-abcdef", "key_id": "k-123"},
        )
        assert "secret" not in event.details
        assert event.details.get("key_id") == "k-123"

    def test_credential_field_stripped(self) -> None:
        writer = AuditWriter()
        event = writer.create(
            uuid4(), "auth.login", "session",
            details={"credential": "password123", "ip": "10.0.0.1"},
        )
        assert "credential" not in event.details
        assert event.details.get("ip") == "10.0.0.1"

    def test_authorization_field_stripped(self) -> None:
        writer = AuditWriter()
        event = writer.create(
            uuid4(), "object.head", "file_object",
            details={"authorization": "SigV4 signed-headers", "key": "data/file.txt"},
        )
        assert "authorization" not in event.details
        assert event.details.get("key") == "data/file.txt"

    def test_safe_fields_preserved(self) -> None:
        writer = AuditWriter()
        event = writer.create(
            uuid4(), "file.upload", "file_object",
            details={
                "size": 1024,
                "content_type": "image/png",
                "tenant_id": str(uuid4()),
            },
        )
        assert event.details["size"] == 1024
        assert event.details["content_type"] == "image/png"

    def test_serialize_excludes_credentials(self) -> None:
        writer = AuditWriter()
        event = writer.create(
            uuid4(), "test", "test",
            details={"password": "secret", "name": "ok"},
        )
        serialized = writer.serialize(event)
        parsed = json.loads(serialized)
        assert "password" not in json.dumps(parsed)
        assert "secret" not in json.dumps(parsed)


class TestAuditFingerprintIsOneWay:
    """Fingerprint must be irreversible — no plaintext recovery."""

    def test_fingerprint_is_deterministic(self) -> None:
        a = AuditWriter.fingerprint("hello")
        b = AuditWriter.fingerprint("hello")
        assert a == b

    def test_fingerprint_differs_for_different_input(self) -> None:
        a = AuditWriter.fingerprint("hello")
        b = AuditWriter.fingerprint("world")
        assert a != b

    def test_fingerprint_is_sha256_hex(self) -> None:
        value = "test-value"
        fp = AuditWriter.fingerprint(value)
        expected = hashlib.sha256(value.encode()).hexdigest()
        assert fp == expected
        assert len(fp) == 64  # SHA-256 hex is 64 chars


class TestErrorResponseNoSensitiveData:
    """Error responses must not leak secrets, stack traces, or internal paths."""

    def test_api_error_no_internal_details(self) -> None:
        from s3mp.common.errors import ApiError
        err = ApiError("forbidden", "Access denied", status_code=403)
        assert err.code == "forbidden"
        assert "trace" not in err.message.lower()
        assert "stack" not in err.message.lower()

    def test_unhandled_error_returns_generic_message(self) -> None:
        from unittest.mock import MagicMock

        from s3mp.common.errors import _body
        request = MagicMock()
        request.state.request_id = "req-001"
        body = _body(request, "internal_error", "An internal error occurred")
        assert body["code"] == "internal_error"
        assert body["message"] == "An internal error occurred"
        # generic message — no stack trace or internal path
        assert "\\" not in body["message"]
        assert "/" not in body["message"]