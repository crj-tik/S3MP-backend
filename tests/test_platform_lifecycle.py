"""Platform lifecycle services retain the global/tenant authority boundary."""

import asyncio
import sys
from datetime import datetime, timedelta
from types import CoroutineType
from uuid import UUID, uuid4

import pytest

from s3mp.common.errors import ApiError
from s3mp.platform import scheduler
from s3mp.platform.application.baseline import SUPPORT_ROLE_PERMISSIONS
from s3mp.platform.application.support_access import SupportAccessService
from s3mp.platform.application.tenant_lifecycle import PlatformTenantLifecycleService
from s3mp.platform.domain.context import PlatformContext


class TenantStore:
    async def list_platform_tenants(
        self, **_kwargs: object
    ) -> tuple[list[dict[str, object]], None]:
        return [], None

    async def get_platform_tenant(self, _tenant_id: UUID) -> dict[str, object] | None:
        return None

    async def create_platform_tenant(self, **kwargs: object) -> dict[str, object]:
        return kwargs

    async def update_platform_tenant(self, **kwargs: object) -> dict[str, object] | None:
        return kwargs

    async def list_platform_accounts(
        self, **_kwargs: object
    ) -> tuple[list[dict[str, object]], None]:
        return [], None


class HistoricalTenantStore(TenantStore):
    async def list_platform_tenants(self, **kwargs: object) -> tuple[list[dict[str, object]], None]:
        return [{"id": str(uuid4()), "status": "deleted"}], None


class SupportStore:
    def __init__(self) -> None:
        self.approver: UUID | None = None

    async def request_support_access(self, **kwargs: object) -> dict[str, object]:
        return kwargs

    async def approve_support_access(self, **kwargs: object) -> dict[str, object] | None:
        self.approver = kwargs["approver_user_id"]  # type: ignore[assignment]
        return kwargs

    async def revoke_support_access(self, **_kwargs: object) -> bool:
        return True

    async def expire_support_access(self, **_kwargs: object) -> int:
        return 0


def platform_context() -> PlatformContext:
    return PlatformContext(uuid4(), uuid4(), frozenset({"platform.tenants.manage"}))


@pytest.mark.asyncio
async def test_platform_tenant_creation_delegates_only_the_initial_admin_identity() -> None:
    service = PlatformTenantLifecycleService(TenantStore())
    context = platform_context()
    initial_admin = uuid4()

    created = await service.create_tenant(
        context, slug="platform-test", name="Platform test", initial_admin_user_id=initial_admin
    )

    assert created["actor_user_id"] == context.user_id
    assert created["initial_admin_user_id"] == initial_admin


@pytest.mark.asyncio
async def test_historical_tenant_listing_requires_platform_audit_permission() -> None:
    service = PlatformTenantLifecycleService(HistoricalTenantStore())
    with pytest.raises(ApiError) as raised:
        await service.list_tenants(
            PlatformContext(uuid4(), uuid4(), frozenset({"platform.tenants.read"})),
            limit=20,
            cursor=None,
            include_deleted=True,
        )
    assert raised.value.code == "permission_denied"

    result, _ = await service.list_tenants(
        PlatformContext(
            uuid4(), uuid4(), frozenset({"platform.tenants.read", "platform.audit.read"})
        ),
        limit=20,
        cursor=None,
        include_deleted=True,
    )
    assert result[0]["status"] == "deleted"


@pytest.mark.asyncio
async def test_support_access_rejects_an_expiry_without_timezone_before_persistence() -> None:
    service = SupportAccessService(SupportStore())

    with pytest.raises(ApiError) as raised:
        await service.request(
            platform_context(),
            tenant_id=uuid4(),
            reason="diagnose",
            expires_at=datetime.now() - timedelta(seconds=1),
        )

    assert raised.value.code == "validation_failed"


@pytest.mark.asyncio
async def test_support_access_requires_an_independent_approver() -> None:
    requester = uuid4()

    class SameUserStore(SupportStore):
        async def approve_support_access(self, **kwargs: object) -> dict[str, object] | None:
            if kwargs["approver_user_id"] == requester:
                raise ValueError("support access requires a different approver")
            return await super().approve_support_access(**kwargs)

    service = SupportAccessService(SameUserStore())
    with pytest.raises(ApiError) as raised:
        await service.approve(PlatformContext(requester, uuid4(), frozenset()), uuid4())

    assert raised.value.code == "conflict"


def test_support_role_is_read_only_and_excludes_file_and_credential_permissions() -> None:
    assert all(
        permission.endswith(".read") or permission == "audit.read"
        for permission in SUPPORT_ROLE_PERMISSIONS
    )
    assert not any(permission.startswith("files.") for permission in SUPPORT_ROLE_PERMISSIONS)
    assert "api_keys.manage" not in SUPPORT_ROLE_PERMISSIONS
    assert not any(
        permission.startswith("storage_connections.manage")
        for permission in SUPPORT_ROLE_PERMISSIONS
    )


def test_scheduler_healthcheck_entrypoint_runs_one_expiry_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked: list[str] = []

    def run(coroutine: object) -> None:
        assert isinstance(coroutine, CoroutineType)
        invoked.append(coroutine.cr_code.co_name)
        coroutine.close()

    monkeypatch.setattr(sys, "argv", ["scheduler", "--once"])
    monkeypatch.setattr(asyncio, "run", run)

    scheduler.main()

    assert invoked == ["run_once"]
