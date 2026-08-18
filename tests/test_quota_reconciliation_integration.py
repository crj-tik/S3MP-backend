from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from _infrastructure import delete_tenant, real_engine, real_session_factory, seed_tenant
from s3mp.common.errors import ApiError
from s3mp.governance.application.reconciliation_service import QuotaReconciliationService
from s3mp.governance.infrastructure.models import QuotaReconciliationRunModel


class FailingInventory:
    async def list_objects(
        self,
        _prefix: str = "",
        *,
        continuation_token: str | None = None,
        max_keys: int = 1000,
    ) -> tuple[list[Any], str | None]:
        raise RuntimeError("provider unavailable")


class TwoPageInventory:
    def __init__(self) -> None:
        self.calls = 0

    async def list_objects(
        self,
        _prefix: str = "",
        *,
        continuation_token: str | None = None,
        max_keys: int = 1000,
    ) -> tuple[list[Any], str | None]:
        self.calls += 1
        return ([], "page-1") if self.calls == 1 else ([], None)


class SerializedInventory:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def list_objects(
        self,
        _prefix: str = "",
        *,
        continuation_token: str | None = None,
        max_keys: int = 1000,
    ) -> tuple[list[Any], str | None]:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.05)
            return [], None
        finally:
            self.active -= 1


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = real_engine()
    yield eng
    await eng.dispose()


@pytest.mark.asyncio
async def test_provider_failure_is_persisted_as_failed_run(engine: AsyncEngine) -> None:
    tenant_id = uuid4()
    await seed_tenant(engine, tenant_id)
    try:
        service = QuotaReconciliationService(
            real_session_factory(engine), FailingInventory(), authorizer=None
        )
        with pytest.raises(RuntimeError, match="provider unavailable"):
            await service.reconcile_internal(tenant_id)

        async with real_session_factory(engine)() as session:
            run = await session.scalar(
                select(QuotaReconciliationRunModel)
                .where(QuotaReconciliationRunModel.tenant_id == tenant_id)
                .order_by(QuotaReconciliationRunModel.created_at.desc())
            )
        assert run is not None
        assert run.status == "failed"
        assert run.error_code == "RuntimeError"
        assert run.error_message == "provider unavailable"
    finally:
        await delete_tenant(engine, tenant_id)


@pytest.mark.asyncio
async def test_reconciliation_persists_each_provider_page_progress(engine: AsyncEngine) -> None:
    tenant_id = uuid4()
    await seed_tenant(engine, tenant_id)
    provider = TwoPageInventory()
    try:
        service = QuotaReconciliationService(
            real_session_factory(engine), provider, authorizer=None
        )
        result = await service.reconcile_internal(tenant_id)

        async with real_session_factory(engine)() as session:
            run = await session.get(QuotaReconciliationRunModel, UUID(result["id"]))
        assert run is not None
        assert run.status == "completed"
        assert run.attempt_count == 2
        assert run.provider_cursor is None
    finally:
        await delete_tenant(engine, tenant_id)


@pytest.mark.asyncio
async def test_same_tenant_reconciliation_workers_are_serialized(engine: AsyncEngine) -> None:
    tenant_id = uuid4()
    await seed_tenant(engine, tenant_id)
    provider = SerializedInventory()
    try:
        factory = real_session_factory(engine)
        first = QuotaReconciliationService(factory, provider, authorizer=None)
        second = QuotaReconciliationService(factory, provider, authorizer=None)
        results = await asyncio.gather(
            first.reconcile_internal(tenant_id), second.reconcile_internal(tenant_id)
        )

        assert len(results) == 2
        assert provider.max_active == 1
    finally:
        await delete_tenant(engine, tenant_id)


@pytest.mark.asyncio
async def test_reconciliation_idempotency_key_returns_same_run(engine: AsyncEngine) -> None:
    tenant_id = uuid4()
    await seed_tenant(engine, tenant_id)
    try:
        service = QuotaReconciliationService(
            real_session_factory(engine), TwoPageInventory(), authorizer=None
        )
        first = await service.reconcile_internal(tenant_id, idempotency_key="apply-check-1")
        second = await service.reconcile_internal(tenant_id, idempotency_key="apply-check-1")
        assert first["id"] == second["id"]
        assert second["status"] == "completed"
    finally:
        await delete_tenant(engine, tenant_id)


@pytest.mark.asyncio
async def test_reconciliation_idempotency_key_rejects_scope_reuse(engine: AsyncEngine) -> None:
    tenant_id = uuid4()
    await seed_tenant(engine, tenant_id)
    try:
        service = QuotaReconciliationService(
            real_session_factory(engine), TwoPageInventory(), authorizer=None
        )
        await service.reconcile_internal(tenant_id, idempotency_key="scope-check-1")
        with pytest.raises(ApiError, match="different reconciliation scope"):
            await service.reconcile_internal(
                tenant_id,
                application_id=str(uuid4()),
                idempotency_key="scope-check-1",
            )
    finally:
        await delete_tenant(engine, tenant_id)
