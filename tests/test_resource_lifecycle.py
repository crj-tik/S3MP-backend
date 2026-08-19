"""Service-level lifecycle state-machine and restore precondition coverage."""

from uuid import UUID, uuid4

import pytest

from s3mp.applications.application.application_service import ApplicationService
from s3mp.applications.infrastructure.models import ApplicationStatus
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext


class LifecycleStore:
    def __init__(self) -> None:
        self.application_id = uuid4()
        self.deleted: tuple[UUID, str] | None = None
        self.restored = False
        self.restore_error: ValueError | None = None

    async def list_apps(
        self,
        _tenant_id: UUID,
        _limit: int,
        _cursor: str | None,
        _status: ApplicationStatus = ApplicationStatus.ACTIVE,
    ) -> tuple[list[dict[str, object]], str | None]:
        return [], None

    async def get_app(self, _tenant_id: UUID, _app_id: UUID) -> dict[str, object] | None:
        return None

    async def create_app(
        self, _tenant_id: UUID, name: str, principal_id: UUID
    ) -> dict[str, object]:
        return {"id": str(self.application_id), "name": name, "principal_id": str(principal_id)}

    async def update_app(
        self, _tenant_id: UUID, _app_id: UUID, _name: str | None
    ) -> dict[str, object] | None:
        return None

    async def list_active_owners(self, _tenant_id: UUID, _app_id: UUID) -> list[UUID]:
        return [self.principal_id]

    async def list_owner_summaries(
        self, _tenant_id: UUID, _app_id: UUID
    ) -> list[dict[str, str]]:
        return []

    async def delete_app(
        self, _tenant_id: UUID, app_id: UUID, _actor: UUID, reason: str
    ) -> dict[str, object]:
        self.deleted = (app_id, reason)
        return {"id": str(app_id), "status": "deleted"}

    async def restore_app(
        self, _tenant_id: UUID, _app_id: UUID, _actor: UUID, _reason: str
    ) -> dict[str, object]:
        if self.restore_error is not None:
            raise self.restore_error
        self.restored = True
        return {"id": str(self.application_id), "status": "active"}

    async def takeover_app(
        self, _tenant_id: UUID, _app_id: UUID, _owner_principal_id: UUID, _reason: str
    ) -> dict[str, object] | None:
        return {"id": str(self.application_id), "status": "active"}

    async def list_owners(self, _tenant_id: UUID, _app_id: UUID) -> list[UUID]:
        return []

    async def recompute_owner_state_for_principal(
        self, _tenant_id: UUID, _owner_principal_id: UUID
    ) -> int:
        return 0

    async def scan_ownerless_applications(self, _tenant_id: UUID) -> int:
        return 0

    def __post_init__(self) -> None:
        self.principal_id = uuid4()


class Authorizer:
    async def require_permission(self, _context: PrincipalContext, _permission: str) -> None:
        return None


def context(store: LifecycleStore) -> PrincipalContext:
    store.principal_id = uuid4()
    return PrincipalContext(uuid4(), store.principal_id, uuid4(), 1)


@pytest.mark.asyncio
async def test_application_delete_preserves_reason_and_actor_boundary() -> None:
    store = LifecycleStore()
    service = ApplicationService(store, Authorizer())
    ctx = context(store)

    result = await service.delete_app(ctx, store.application_id, "retired by operator")

    assert result["status"] == "deleted"
    assert store.deleted == (store.application_id, "retired by operator")


@pytest.mark.asyncio
async def test_application_restore_keeps_deleted_state_when_preconditions_fail() -> None:
    store = LifecycleStore()
    store.restore_error = ValueError("application restore requires an active Owner")
    service = ApplicationService(store, Authorizer())

    with pytest.raises(ApiError) as raised:
        await service.restore_app(context(store), store.application_id, "owner reassigned")

    assert raised.value.code == "conflict"
    assert store.restored is False
