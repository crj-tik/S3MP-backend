"""Transactional persistence for knowledge extraction tasks and exclusions."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from s3mp.applications.infrastructure.models import ApplicationModel
from s3mp.audit.infrastructure.models import AuditEventModel
from s3mp.common.errors import ApiError
from s3mp.knowledge.domain.exclusions import is_excluded, normalize_directory_path
from s3mp.knowledge.domain.source_hash import SourceChecksumMismatch, normalize_declared_sha256
from s3mp.knowledge.domain.state_machine import assert_transition
from s3mp.knowledge.infrastructure.models import (
    KnowledgeAnalysisTaskModel,
    KnowledgeBatchModel,
    KnowledgeCardModel,
    KnowledgeDeadLetterEventModel,
    KnowledgeEventOutboxModel,
    KnowledgeExtractionExclusionRuleModel,
)
from s3mp.tenant.infrastructure.models import TenantModel  # noqa: F401


class SqlAlchemyKnowledgeStore:
    """Owns transactional state; messages are published only from its outbox."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], redis: Redis | None = None
    ) -> None:
        self._sf = session_factory
        self._redis = redis

    @staticmethod
    def _cache_key(tenant_id: UUID, application_id: UUID) -> str:
        return f"knowledge:exclusion-rules:v1:{tenant_id}:{application_id}"

    async def _cached_rules(self, tenant_id: UUID, application_id: UUID) -> list[str] | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(self._cache_key(tenant_id, application_id))
            if raw is None:
                return None
            parsed = json.loads(raw)
            return (
                parsed
                if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed)
                else None
            )
        except (RedisError, ValueError, TypeError):
            return None

    async def _refresh_rule_cache(self, tenant_id: UUID, application_id: UUID) -> None:
        if self._redis is None:
            return
        async with self._sf() as session:
            rows = (
                await session.scalars(
                    select(KnowledgeExtractionExclusionRuleModel.directory_path).where(
                        KnowledgeExtractionExclusionRuleModel.tenant_id == tenant_id,
                        KnowledgeExtractionExclusionRuleModel.application_id == application_id,
                        KnowledgeExtractionExclusionRuleModel.enabled.is_(True),
                    )
                )
            ).all()
        try:
            await self._redis.set(self._cache_key(tenant_id, application_id), json.dumps(rows))
        except RedisError:
            pass

    @staticmethod
    async def _require_tenant_application(
        session: AsyncSession, tenant_id: UUID, application_id: UUID
    ) -> None:
        exists = await session.scalar(
            select(ApplicationModel.id).where(
                ApplicationModel.tenant_id == tenant_id,
                ApplicationModel.id == application_id,
                ApplicationModel.status == "active",
            )
        )
        if exists is None:
            raise ApiError("resource_not_found", "Application not found", status_code=404)

    async def matching_exclusion(
        self, tenant_id: UUID, application_id: UUID, object_key: str
    ) -> dict[str, Any] | None:
        cached = await self._cached_rules(tenant_id, application_id)
        if cached is not None:
            for path in cached:
                if is_excluded(object_key, path):
                    return {"directory_path": path}
            return None
        async with self._sf() as session:
            rows = (
                await session.scalars(
                    select(KnowledgeExtractionExclusionRuleModel).where(
                        KnowledgeExtractionExclusionRuleModel.tenant_id == tenant_id,
                        KnowledgeExtractionExclusionRuleModel.application_id == application_id,
                        KnowledgeExtractionExclusionRuleModel.enabled.is_(True),
                    )
                )
            ).all()
            for row in rows:
                if is_excluded(object_key, row.directory_path):
                    await self._refresh_rule_cache(tenant_id, application_id)
                    return _rule_dict(row)
        await self._refresh_rule_cache(tenant_id, application_id)
        return None

    async def list_exclusions(self, tenant_id: UUID, application_id: UUID) -> list[dict[str, Any]]:
        async with self._sf() as session:
            await self._require_tenant_application(session, tenant_id, application_id)
            rows = (
                await session.scalars(
                    select(KnowledgeExtractionExclusionRuleModel)
                    .where(
                        KnowledgeExtractionExclusionRuleModel.tenant_id == tenant_id,
                        KnowledgeExtractionExclusionRuleModel.application_id == application_id,
                    )
                    .order_by(KnowledgeExtractionExclusionRuleModel.directory_path)
                )
            ).all()
            return [_rule_dict(row) for row in rows]

    async def create_exclusion(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        directory_path: str,
        rule_source: str,
        created_by_principal_id: UUID | None,
    ) -> dict[str, Any]:
        normalized = normalize_directory_path(directory_path)
        async with self._sf() as session, session.begin():
            await self._require_tenant_application(session, tenant_id, application_id)
            row = await session.scalar(
                select(KnowledgeExtractionExclusionRuleModel).where(
                    KnowledgeExtractionExclusionRuleModel.tenant_id == tenant_id,
                    KnowledgeExtractionExclusionRuleModel.application_id == application_id,
                    KnowledgeExtractionExclusionRuleModel.directory_path == normalized,
                    KnowledgeExtractionExclusionRuleModel.rule_source == rule_source,
                )
            )
            if row is None:
                row = KnowledgeExtractionExclusionRuleModel(
                    tenant_id=tenant_id,
                    application_id=application_id,
                    directory_path=normalized,
                    rule_source=rule_source,
                    created_by_principal_id=created_by_principal_id,
                )
                session.add(row)
                await session.flush()
                session.add(
                    AuditEventModel(
                        tenant_id=tenant_id,
                        actor_principal_id=created_by_principal_id,
                        action="knowledge.exclusion.created",
                        resource_type="knowledge_exclusion_rule",
                        resource_id=str(row.id),
                        details={
                            "application_id": str(application_id),
                            "directory_path": normalized,
                            "rule_source": rule_source,
                        },
                    )
                )
            result = _rule_dict(row)
        await self._refresh_rule_cache(tenant_id, application_id)
        return result

    async def delete_exclusion(
        self,
        tenant_id: UUID,
        application_id: UUID,
        rule_id: UUID,
        rule_source: str,
        actor_principal_id: UUID | None = None,
    ) -> bool:
        async with self._sf() as session, session.begin():
            await self._require_tenant_application(session, tenant_id, application_id)
            row = await session.scalar(
                select(KnowledgeExtractionExclusionRuleModel).where(
                    KnowledgeExtractionExclusionRuleModel.id == rule_id,
                    KnowledgeExtractionExclusionRuleModel.tenant_id == tenant_id,
                    KnowledgeExtractionExclusionRuleModel.application_id == application_id,
                    KnowledgeExtractionExclusionRuleModel.rule_source == rule_source,
                )
            )
            if row is None:
                return False
            await session.delete(row)
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_principal_id=actor_principal_id,
                    action="knowledge.exclusion.deleted",
                    resource_type="knowledge_exclusion_rule",
                    resource_id=str(rule_id),
                    details={
                        "application_id": str(application_id),
                        "directory_path": row.directory_path,
                        "rule_source": rule_source,
                    },
                )
            )
        await self._refresh_rule_cache(tenant_id, application_id)
        return True

    async def create_task(
        self,
        *,
        tenant_id: UUID,
        source_file_id: UUID,
        application_id: UUID,
        storage_space_id: UUID,
        storage_namespace: str,
        object_key: str,
        content_type: str,
        content_hash: str | None,
        contract_version: str,
        contract_manifest_hash: str,
        state: str = "queued",
        failure_reason: str | None = None,
    ) -> dict[str, Any]:
        """Create one task plus durable analysis outbox event, idempotently."""
        async with self._sf() as session, session.begin():
            existing = await session.scalar(
                select(KnowledgeAnalysisTaskModel).where(
                    KnowledgeAnalysisTaskModel.tenant_id == tenant_id,
                    KnowledgeAnalysisTaskModel.source_file_id == source_file_id,
                    KnowledgeAnalysisTaskModel.contract_manifest_hash == contract_manifest_hash,
                )
            )
            if existing is not None:
                return _task_dict(existing)
            task = KnowledgeAnalysisTaskModel(
                tenant_id=tenant_id,
                source_file_id=source_file_id,
                source_application_id=application_id,
                source_storage_space_id=storage_space_id,
                source_storage_namespace=storage_namespace,
                source_object_key=object_key,
                source_content_type=content_type,
                source_content_hash=content_hash,
                source_sha256=normalize_declared_sha256(content_hash),
                contract_version=contract_version,
                contract_manifest_hash=contract_manifest_hash,
                state=state,
                phase="queued" if state == "queued" else state,
                failure_reason=failure_reason,
            )
            session.add(task)
            await session.flush()
            if state == "queued":
                session.add(
                    KnowledgeEventOutboxModel(
                        tenant_id=tenant_id,
                        task_id=task.id,
                        event_type="knowledge.analysis.requested",
                        payload={"tenant_id": str(tenant_id), "task_id": str(task.id)},
                    )
                )
            return _task_dict(task)

    async def claim_task(self, tenant_id: UUID, task_id: UUID) -> dict[str, Any] | None:
        async with self._sf() as session, session.begin():
            task = await session.scalar(
                select(KnowledgeAnalysisTaskModel)
                .where(
                    KnowledgeAnalysisTaskModel.tenant_id == tenant_id,
                    KnowledgeAnalysisTaskModel.id == task_id,
                )
                .with_for_update()
            )
            if task is None or task.state != "queued":
                return None
            assert_transition(task.state, "processing")
            task.state, task.phase = "processing", "fetching"
            task.attempt_count += 1
            task.processing_started_at = datetime.now(UTC)
            task.processing_lease_token = uuid4()
            task.processing_lease_expires_at = task.processing_started_at + timedelta(minutes=30)
            await session.flush()
            return _task_dict(task)

    async def set_task_phase(self, tenant_id: UUID, task_id: UUID, phase: str) -> None:
        async with self._sf() as session, session.begin():
            task = await session.scalar(
                select(KnowledgeAnalysisTaskModel).where(
                    KnowledgeAnalysisTaskModel.tenant_id == tenant_id,
                    KnowledgeAnalysisTaskModel.id == task_id,
                )
            )
            if task is not None and task.state == "processing":
                task.phase = phase

    async def resolve_source_sha256(
        self, tenant_id: UUID, task_id: UUID, source_sha256: str
    ) -> bool:
        """Persist a fetched hash and return whether LLM work remains unique."""
        async with self._sf() as session, session.begin():
            task = await session.scalar(
                select(KnowledgeAnalysisTaskModel)
                .where(
                    KnowledgeAnalysisTaskModel.tenant_id == tenant_id,
                    KnowledgeAnalysisTaskModel.id == task_id,
                )
                .with_for_update()
            )
            if task is None or task.state != "processing":
                return False
            if task.source_sha256 is not None and task.source_sha256 != source_sha256:
                raise SourceChecksumMismatch("declared checksum does not match fetched source")
            duplicate = await session.scalar(
                select(KnowledgeAnalysisTaskModel.id).where(
                    KnowledgeAnalysisTaskModel.tenant_id == tenant_id,
                    KnowledgeAnalysisTaskModel.source_sha256 == source_sha256,
                    KnowledgeAnalysisTaskModel.contract_manifest_hash
                    == task.contract_manifest_hash,
                    KnowledgeAnalysisTaskModel.state == "completed",
                    KnowledgeAnalysisTaskModel.id != task.id,
                )
            )
            task.source_sha256 = source_sha256
            return duplicate is None

    async def complete_s3_batch(
        self,
        tenant_id: UUID,
        task_id: UUID,
        result: dict[str, Any],
    ) -> None:
        """Persist a completed S3 batch and its index outbox events atomically."""
        async with self._sf() as session, session.begin():
            task = await session.scalar(
                select(KnowledgeAnalysisTaskModel)
                .where(
                    KnowledgeAnalysisTaskModel.tenant_id == tenant_id,
                    KnowledgeAnalysisTaskModel.id == task_id,
                )
                .with_for_update()
            )
            if task is None:
                return
            batch_id = str(result["batch_id"])
            batch = await session.scalar(
                select(KnowledgeBatchModel).where(
                    KnowledgeBatchModel.tenant_id == tenant_id,
                    KnowledgeBatchModel.batch_id == batch_id,
                )
            )
            if batch is None:
                batch = KnowledgeBatchModel(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    batch_id=batch_id,
                    s3_prefix=str(result["prefix"]),
                    completion_manifest_key=str(result["completion_manifest_key"]),
                )
                session.add(batch)
                await session.flush()
            for record in result["cards"]:
                card = await session.scalar(
                    select(KnowledgeCardModel).where(
                        KnowledgeCardModel.tenant_id == tenant_id,
                        KnowledgeCardModel.batch_id == batch.id,
                        KnowledgeCardModel.card_id == str(record["id"]),
                    )
                )
                if card is None:
                    card = KnowledgeCardModel(
                        tenant_id=tenant_id,
                        batch_id=batch.id,
                        card_id=str(record["id"]),
                        card_type=str(record["type"]),
                        status="draft",
                        s3_key=str(record["s3Key"]),
                        checksum=str(record["checksum"]),
                        source_locations=list(record["sourceLocations"]),
                    )
                    session.add(card)
                    await session.flush()
                event = await session.scalar(
                    select(KnowledgeEventOutboxModel).where(
                        KnowledgeEventOutboxModel.task_id == task.id,
                        KnowledgeEventOutboxModel.card_id == card.id,
                        KnowledgeEventOutboxModel.event_type == "knowledge.index.requested",
                    )
                )
                if event is None:
                    session.add(
                        KnowledgeEventOutboxModel(
                            tenant_id=tenant_id,
                            task_id=task.id,
                            card_id=card.id,
                            event_type="knowledge.index.requested",
                            payload={
                                "tenant_id": str(tenant_id),
                                "task_id": str(task.id),
                                "card_id": str(card.id),
                                "batch_id": batch_id,
                                "s3_key": str(record["s3Key"]),
                                "completion_manifest_key": str(result["completion_manifest_key"]),
                            },
                        )
                    )
            if task.state == "processing":
                assert_transition(task.state, "completed")
                task.state, task.phase, task.failure_reason = "completed", "completed", None
                task.batch_id, task.batch_prefix = batch_id, str(result["prefix"])
                task.processing_started_at, task.completed_at = None, datetime.now(UTC)

    async def set_card_index_state(self, tenant_id: UUID, card_id: UUID, state: str) -> None:
        async with self._sf() as session, session.begin():
            card = await session.scalar(
                select(KnowledgeCardModel).where(
                    KnowledgeCardModel.tenant_id == tenant_id,
                    KnowledgeCardModel.id == card_id,
                )
            )
            if card is not None:
                card.index_state = state

    async def settle_task(
        self, tenant_id: UUID, task_id: UUID, state: str, reason: str | None = None
    ) -> None:
        async with self._sf() as session, session.begin():
            task = await session.scalar(
                select(KnowledgeAnalysisTaskModel)
                .where(
                    KnowledgeAnalysisTaskModel.tenant_id == tenant_id,
                    KnowledgeAnalysisTaskModel.id == task_id,
                )
                .with_for_update()
            )
            if task is None or task.state in {"completed", "skipped", "dead_lettered"}:
                return
            assert_transition(task.state, state)
            task.state, task.phase, task.failure_reason = state, state, reason
            task.processing_started_at = None
            task.processing_lease_token, task.processing_lease_expires_at = None, None
            if state in {"completed", "skipped", "dead_lettered"}:
                task.completed_at = datetime.now(UTC)

    async def schedule_retry(
        self, tenant_id: UUID, task_id: UUID, reason: str, max_retries: int
    ) -> dict[str, Any] | None:
        async with self._sf() as session, session.begin():
            task = await session.scalar(
                select(KnowledgeAnalysisTaskModel)
                .where(
                    KnowledgeAnalysisTaskModel.tenant_id == tenant_id,
                    KnowledgeAnalysisTaskModel.id == task_id,
                )
                .with_for_update()
            )
            if task is None or task.state != "processing":
                return None
            if task.attempt_count >= max_retries:
                task.state, task.phase, task.failure_reason = (
                    "dead_lettered",
                    "dead_lettered",
                    reason,
                )
                task.completed_at, task.processing_started_at = datetime.now(UTC), None
                return _task_dict(task)
            assert_transition(task.state, "queued")
            task.state, task.phase, task.failure_reason = "queued", "queued", reason
            task.processing_started_at = None
            task.processing_lease_token, task.processing_lease_expires_at = None, None
            return _task_dict(task)

    async def recover_stale_processing(
        self, timeout_seconds: int, max_retries: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        _ = timeout_seconds
        async with self._sf() as session, session.begin():
            rows: Sequence[KnowledgeAnalysisTaskModel] = (
                await session.scalars(
                    select(KnowledgeAnalysisTaskModel)
                    .where(
                        KnowledgeAnalysisTaskModel.state == "processing",
                        KnowledgeAnalysisTaskModel.processing_lease_expires_at < datetime.now(UTC),
                    )
                    .order_by(KnowledgeAnalysisTaskModel.processing_started_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            recovered: list[dict[str, Any]] = []
            for task in rows:
                task.recovery_attempt_count += 1
                if task.attempt_count >= max_retries:
                    task.state, task.phase, task.failure_reason = (
                        "dead_lettered",
                        "dead_lettered",
                        "processing_timeout",
                    )
                    task.completed_at = datetime.now(UTC)
                else:
                    task.state, task.phase, task.failure_reason = (
                        "queued",
                        "queued",
                        "processing_timeout",
                    )
                    session.add(
                        KnowledgeEventOutboxModel(
                            tenant_id=task.tenant_id,
                            task_id=task.id,
                            event_type="knowledge.analysis.requested",
                            payload={"tenant_id": str(task.tenant_id), "task_id": str(task.id)},
                        )
                    )
                task.processing_started_at = None
                task.processing_lease_token, task.processing_lease_expires_at = None, None
                recovered.append(_task_dict(task))
            return recovered

    async def claim_outbox_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """Lease unpublished events so competing publishers cannot duplicate ownership."""
        lease_until = datetime.now(UTC) + timedelta(minutes=1)
        async with self._sf() as session, session.begin():
            rows: Sequence[KnowledgeEventOutboxModel] = (
                await session.scalars(
                    select(KnowledgeEventOutboxModel)
                    .where(
                        KnowledgeEventOutboxModel.published_at.is_(None),
                        or_(
                            KnowledgeEventOutboxModel.publish_lease_expires_at.is_(None),
                            KnowledgeEventOutboxModel.publish_lease_expires_at < datetime.now(UTC),
                        ),
                    )
                    .order_by(KnowledgeEventOutboxModel.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                row.publish_lease_expires_at = lease_until
                row.publish_attempt_count += 1
            return [_outbox_dict(row) for row in rows]

    async def mark_outbox_published(self, event_id: UUID) -> None:
        async with self._sf() as session, session.begin():
            row = await session.get(KnowledgeEventOutboxModel, event_id, with_for_update=True)
            if row is not None:
                row.published_at, row.publish_lease_expires_at = datetime.now(UTC), None

    async def release_outbox_event(self, event_id: UUID) -> None:
        async with self._sf() as session, session.begin():
            row = await session.get(KnowledgeEventOutboxModel, event_id, with_for_update=True)
            if row is not None and row.published_at is None:
                row.publish_lease_expires_at = None

    async def record_dead_letter(
        self, tenant_id: UUID, task_id: UUID | None, details: dict[str, object]
    ) -> None:
        async with self._sf() as session, session.begin():
            session.add(
                KnowledgeDeadLetterEventModel(
                    tenant_id=tenant_id,
                    task_id=task_id,
                    event_type="knowledge.analysis.dead_lettered",
                    details=details,
                )
            )

    async def replay_dead_letter(self, tenant_id: UUID, task_id: UUID) -> bool:
        """Controlled operator primitive; no HTTP/UI surface is exposed."""
        async with self._sf() as session, session.begin():
            task = await session.scalar(
                select(KnowledgeAnalysisTaskModel)
                .where(
                    KnowledgeAnalysisTaskModel.tenant_id == tenant_id,
                    KnowledgeAnalysisTaskModel.id == task_id,
                    KnowledgeAnalysisTaskModel.state == "dead_lettered",
                )
                .with_for_update()
            )
            if task is None:
                return False
            task.state, task.phase = "queued", "queued"
            task.failure_reason, task.processing_started_at = "operator_replay", None
            task.attempt_count = 0
            session.add(
                KnowledgeEventOutboxModel(
                    tenant_id=tenant_id,
                    task_id=task_id,
                    event_type="knowledge.analysis.requested",
                    payload={"tenant_id": str(tenant_id), "task_id": str(task_id), "replay": True},
                )
            )
            return True


def _rule_dict(row: KnowledgeExtractionExclusionRuleModel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "application_id": str(row.application_id),
        "directory_path": row.directory_path,
        "rule_source": row.rule_source,
        "enabled": row.enabled,
        "created_at": row.created_at,
    }


def _task_dict(row: KnowledgeAnalysisTaskModel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "source_file_id": str(row.source_file_id) if row.source_file_id else None,
        "source_application_id": str(row.source_application_id)
        if row.source_application_id
        else None,
        "source_storage_space_id": str(row.source_storage_space_id)
        if row.source_storage_space_id
        else None,
        "source_storage_namespace": row.source_storage_namespace,
        "source_object_key": row.source_object_key,
        "source_content_type": row.source_content_type,
        "source_content_hash": row.source_content_hash,
        "source_sha256": row.source_sha256,
        "processing_lease_token": str(row.processing_lease_token)
        if row.processing_lease_token
        else None,
        "contract_version": row.contract_version,
        "contract_manifest_hash": row.contract_manifest_hash,
        "state": row.state,
        "phase": row.phase,
        "attempt_count": row.attempt_count,
        "batch_id": row.batch_id,
        "batch_prefix": row.batch_prefix,
        "failure_reason": row.failure_reason,
    }


def _outbox_dict(row: KnowledgeEventOutboxModel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "task_id": str(row.task_id),
        "event_type": row.event_type,
        "payload": dict(row.payload),
        "publish_attempt_count": row.publish_attempt_count,
    }
