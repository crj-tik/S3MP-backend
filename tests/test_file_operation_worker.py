from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from s3mp.authorization.domain.evaluator import Binding, Decision
from s3mp.files.application.operation_worker import FileOperationWorker
from s3mp.storage.domain.policy import ProviderTarget
from s3mp.storage.infrastructure.minio import ObjectMetadata


class Store:
    def __init__(self, operation: dict[str, Any]) -> None:
        self.operation = operation
        self.finished: list[tuple[str, str | None]] = []
        self.renewed = 0

    async def claim_operations(self, worker_id: str, limit: int = 10) -> list[dict[str, Any]]:
        return [self.operation]

    async def finish_operation(
        self, tenant_id: UUID, operation_id: UUID, status: str, reason: str | None = None
    ) -> None:
        self.finished.append((status, reason))

    async def renew_operation_lease(
        self, tenant_id: UUID, operation_id: UUID, worker_id: str
    ) -> bool:
        self.renewed += 1
        return True


class Spaces:
    async def get_space(self, tenant_id: UUID, space_id: UUID) -> dict[str, Any]:
        return {
            "id": str(space_id),
            "tenant_id": str(tenant_id),
            "bucket": "s3mp-dev",
            "root_prefix": "tenant",
        }


class Auth:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow

    async def bindings_for(
        self,
        tenant_id: UUID,
        principal_id: UUID,
        storage_space_id: UUID,
        *,
        subject_kind: str = "human",
    ) -> list[Binding]:
        return [
            Binding(
                uuid4(),
                permission,
                Decision.ALLOW if self.allow else Decision.DENY,
                None,
                datetime.now(UTC) - timedelta(minutes=1),
                datetime.now(UTC) + timedelta(minutes=1),
                "test",
                storage_space_id,
            )
            for permission in ("files.read", "files.write", "files.delete")
        ]


class Principals:
    principal_id: str

    async def get_principal(self, tenant_id: UUID, principal_id: UUID) -> dict[str, Any]:
        self.principal_id = str(principal_id)
        return {"enabled": True}

    async def get_membership_state(self, tenant_id: UUID, membership_id: UUID) -> dict[str, Any]:
        return {
            "id": str(membership_id),
            "principal_id": self.principal_id,
            "status": "active",
            "authorization_version": 1,
            "expires_at": None,
        }


class Objects:
    def __init__(self) -> None:
        self.copies: list[tuple[ProviderTarget, ProviderTarget]] = []
        self.objects = {"v1/tenants"}

    async def copy(self, source: ProviderTarget, destination: ProviderTarget) -> ObjectMetadata:
        self.copies.append((source, destination))
        self.objects.add(destination.key)
        return ObjectMetadata(destination.key, 0, None, None)

    async def delete(self, target: ProviderTarget) -> None:
        return None

    async def head(self, target: ProviderTarget) -> ObjectMetadata | None:
        return ObjectMetadata(target.key, 0, None, None) if target.key in self.objects else None


class Keys:
    principal_id: str
    application_id: str

    def __init__(self, active: bool = True) -> None:
        self.active = active

    async def get_key_state(self, tenant_id: UUID, key_id: UUID) -> dict[str, Any]:
        return {
            "status": "active" if self.active else "revoked",
            "application_status": "active",
            "principal_enabled": True,
            "principal_id": self.principal_id,
            "application_id": self.application_id,
            "expires_at": None,
            "scopes": ["files.read", "files.write"],
        }


def operation() -> dict[str, Any]:
    tenant, principal, space, membership = uuid4(), uuid4(), uuid4(), uuid4()
    return {
        "id": str(uuid4()),
        "tenant_id": str(tenant),
        "principal_id": str(principal),
        "membership_id": str(membership),
        "storage_space_id": str(space),
        "operation_type": "copy",
        "source_key": "a",
        "destination_key": "b",
        "keys": [],
        "authorization_version": 1,
        "provider_target_version": 1,
        "authorization_evidence": {"subject_kind": "human"},
    }


@pytest.mark.asyncio
async def test_worker_never_mutates_legacy_provider_targets() -> None:
    record, objects = operation(), Objects()
    record["provider_target_version"] = 0
    store = Store(record)
    await FileOperationWorker(store, Spaces(), Auth(), Principals(), objects).run_once("worker")
    assert objects.copies == []
    assert store.finished == [("cancelled", "legacy_provider_target")]


@pytest.mark.asyncio
async def test_worker_cancels_human_operation_without_membership() -> None:
    record, objects = operation(), Objects()
    record.pop("membership_id")
    store = Store(record)
    await FileOperationWorker(store, Spaces(), Auth(), Principals(), objects).run_once("worker")
    assert objects.copies == []
    assert store.finished == [("cancelled", "subject_inactive_or_stale")]


@pytest.mark.asyncio
async def test_worker_cancels_when_membership_authorization_version_changes() -> None:
    class StaleMembership(Principals):
        async def get_membership_state(
            self, tenant_id: UUID, membership_id: UUID
        ) -> dict[str, Any]:
            state = await super().get_membership_state(tenant_id, membership_id)
            state["authorization_version"] = 2
            return state

    record, objects = operation(), Objects()
    store = Store(record)
    await FileOperationWorker(store, Spaces(), Auth(), StaleMembership(), objects).run_once(
        "worker"
    )
    assert objects.copies == []
    assert store.finished == [("cancelled", "subject_inactive_or_stale")]


@pytest.mark.asyncio
async def test_worker_cancels_deleted_principal_before_provider_call() -> None:
    class DeletedPrincipal(Principals):
        async def get_principal(
            self, tenant_id: UUID, principal_id: UUID
        ) -> dict[str, Any]:
            self.principal_id = str(principal_id)
            return {"enabled": False, "status": "deleted"}

    record, objects = operation(), Objects()
    store = Store(record)
    await FileOperationWorker(
        store, Spaces(), Auth(), DeletedPrincipal(), objects
    ).run_once("worker")
    assert objects.copies == []
    assert store.finished == [("cancelled", "subject_inactive_or_stale")]


@pytest.mark.asyncio
async def test_worker_executes_authorized_copy() -> None:
    record, store, objects = operation(), None, Objects()
    objects.objects = {
        f"v1/tenants/{record['tenant_id']}/spaces/{record['storage_space_id']}/tenant/a"
    }
    store = Store(record)
    await FileOperationWorker(store, Spaces(), Auth(), Principals(), objects).run_once("worker")
    assert objects.copies[0][0].bucket == "s3mp-dev"
    assert objects.copies[0][0].key.endswith("/tenant/a")
    assert objects.copies[0][1].key.endswith("/tenant/b")
    assert store.finished == [("succeeded", None)]


@pytest.mark.asyncio
async def test_worker_cancels_revoked_permission_before_provider_call() -> None:
    record, store, objects = operation(), None, Objects()
    store = Store(record)
    await FileOperationWorker(store, Spaces(), Auth(False), Principals(), objects).run_once(
        "worker"
    )
    assert objects.copies == []
    assert store.finished == [("cancelled", "authorization_revoked")]


@pytest.mark.asyncio
async def test_worker_cancels_revoked_api_key_before_provider_call() -> None:
    record, store, objects = operation(), None, Objects()
    record["authorization_evidence"] = {
        "subject_kind": "application",
        "api_key_id": str(uuid4()),
        "application_id": str(uuid4()),
        "api_key_scopes": ["files.read", "files.write"],
    }
    keys = Keys(False)
    keys.principal_id, keys.application_id = (
        record["principal_id"],
        record["authorization_evidence"]["application_id"],
    )
    store = Store(record)
    await FileOperationWorker(store, Spaces(), Auth(), Principals(), objects, keys).run_once(
        "worker"
    )
    assert objects.copies == []
    assert store.finished == [("cancelled", "subject_inactive_or_stale")]


@pytest.mark.asyncio
async def test_worker_recovers_after_move_provider_success_before_db_commit() -> None:
    record, objects = operation(), Objects()
    record["operation_type"] = "move"
    objects.objects = {
        f"v1/tenants/{record['tenant_id']}/spaces/{record['storage_space_id']}/tenant/b"
    }
    store = Store(record)
    await FileOperationWorker(store, Spaces(), Auth(), Principals(), objects).run_once("worker")
    assert objects.copies == []
    assert store.finished == [("succeeded", None)]


@pytest.mark.asyncio
async def test_move_delete_failure_is_partial_failure() -> None:
    class DeleteFails(Objects):
        async def delete(self, target: ProviderTarget) -> None:
            raise RuntimeError("provider unavailable")

    record, objects = operation(), DeleteFails()
    record["operation_type"] = "move"
    objects.objects = {
        f"v1/tenants/{record['tenant_id']}/spaces/{record['storage_space_id']}/tenant/a"
    }
    store = Store(record)
    await FileOperationWorker(store, Spaces(), Auth(), Principals(), objects).run_once("worker")
    assert store.finished == [("partial_failure", "source_delete_failed")]
