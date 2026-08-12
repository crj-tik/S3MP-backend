from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from s3mp.applications.domain.credentials import (
    ApiKeyCredentialService,
    ApiKeyRateLimiter,
    effective_key_scopes,
    key_is_usable,
    orphaned_application,
    parse_credential,
    require_scope_intersection,
    revoke_key,
)


def test_api_key_is_high_entropy_and_secret_verification_is_one_way() -> None:
    service = ApiKeyCredentialService(b"p" * 32)
    issued = service.issue()
    key_id, secret = parse_credential(f"S3MP-Key {issued.credential}")

    assert key_id == issued.key_id
    assert secret == issued.secret
    assert service.verify(secret, service.digest(secret))
    assert not service.verify("wrong", service.digest(secret))
    assert issued.secret not in service.digest(secret).hex()


def test_api_key_lifecycle_scope_and_orphan_rules() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert key_is_usable(status="active", expires_at=now + timedelta(hours=1), now=now)
    assert not key_is_usable(status="revoked", expires_at=now + timedelta(hours=1), now=now)
    assert not key_is_usable(status="active", expires_at=now, now=now)
    require_scope_intersection({"files.read", "files.list"}, {"files.read"})
    with pytest.raises(PermissionError):
        require_scope_intersection({"files.read"}, {"files.write"})
    assert orphaned_application({uuid4()}, set())
    assert effective_key_scopes(
        {"files.read", "files.write"},
        {"files.read", "files.write"},
        {"files.read"},
        {"files.read"},
        {"files.read"},
    ) == {"files.read"}
    assert revoke_key(
        revoked_at=now, issued_until=now + timedelta(minutes=5)
    ) == now + timedelta(minutes=5)


@pytest.mark.asyncio
async def test_api_key_rate_limits_key_application_and_tenant() -> None:
    limiter = ApiKeyRateLimiter(limit=1)
    application_id, tenant_id = uuid4(), uuid4()

    assert await limiter.allow(key_id="k", application_id=application_id, tenant_id=tenant_id)
    assert not await limiter.allow(key_id="k", application_id=application_id, tenant_id=tenant_id)
