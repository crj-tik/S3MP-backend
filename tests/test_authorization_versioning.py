from uuid import uuid4

import pytest

from s3mp.authorization.application.versioning import (
    InMemoryAuthorizationVersionStore,
    StaleAuthorization,
    VersionedAuthorizationCache,
    require_current_version,
)


@pytest.mark.asyncio
async def test_authorization_version_bumps_and_invalidates_old_values() -> None:
    tenant_id = uuid4()
    store = InMemoryAuthorizationVersionStore()
    cache = VersionedAuthorizationCache()

    assert await store.current(tenant_id) == 1
    cache.put("cursor", "payload", 1)
    assert await store.bump(tenant_id) == 2
    assert cache.get("cursor", 2) is None
    assert cache.get("cursor", 1) == "payload"


def test_stale_session_cursor_or_task_is_rejected() -> None:
    require_current_version(3, 3)
    with pytest.raises(StaleAuthorization):
        require_current_version(2, 3)
