"""Analysis-task executor used by the dedicated RabbitMQ consumer."""

from __future__ import annotations

import hashlib
from typing import Any, Protocol
from uuid import UUID

from s3mp.knowledge.application.batch_writer import S3KnowledgeBatchWriter
from s3mp.knowledge.application.llm_client import LLMExtractionResult
from s3mp.knowledge.application.prompting import assemble_prompt, validate_draft
from s3mp.knowledge.application.text_extraction import (
    ExtractionLimitExceeded,
    OcrRequiredDocument,
    UnsupportedDocumentType,
    chunk_segments,
    extract_text,
)
from s3mp.knowledge.contracts import KnowledgeContract
from s3mp.knowledge.domain.source_hash import SourceChecksumMismatch
from s3mp.storage.domain.policy import ProviderTarget, derive_provider_target


class AnalysisTaskStore(Protocol):
    async def set_task_phase(self, tenant_id: UUID, task_id: UUID, phase: str) -> None: ...

    async def matching_exclusion(
        self, tenant_id: UUID, application_id: UUID, object_key: str
    ) -> dict[str, Any] | None: ...

    async def resolve_source_sha256(
        self, tenant_id: UUID, task_id: UUID, source_sha256: str
    ) -> bool: ...

    async def complete_s3_batch(
        self, tenant_id: UUID, task_id: UUID, result: dict[str, Any]
    ) -> None: ...


class AnalysisObjectStorage(Protocol):
    async def get(self, target: ProviderTarget, *, max_bytes: int) -> bytes | None: ...


class AnalysisLLM(Protocol):
    async def extract(self, prompt: str) -> LLMExtractionResult: ...


class KnowledgeAnalysisExecutor:
    def __init__(
        self,
        *,
        store: AnalysisTaskStore,
        object_storage: AnalysisObjectStorage,
        llm: AnalysisLLM,
        writer: S3KnowledgeBatchWriter,
        contract: KnowledgeContract,
        bucket: str,
        max_source_bytes: int,
        max_extracted_characters: int,
        chunk_characters: int,
    ) -> None:
        self._store, self._storage, self._llm = store, object_storage, llm
        self._writer, self._contract, self._bucket = writer, contract, bucket
        self._max_source_bytes = max_source_bytes
        self._max_extracted_characters = max_extracted_characters
        self._chunk_characters = chunk_characters

    async def execute(self, task: dict[str, Any]) -> tuple[str, str | None]:
        tenant_id, task_id = UUID(task["tenant_id"]), UUID(task["id"])
        application_id = task.get("source_application_id")
        if application_id:
            rule = await self._store.matching_exclusion(
                tenant_id, UUID(application_id), task["source_object_key"]
            )
            if rule is not None:
                return "skipped", "excluded_before_fetch"
        await self._store.set_task_phase(tenant_id, task_id, "fetching")
        target = derive_provider_target(
            tenant_id=tenant_id,
            storage_space_id=UUID(task["source_storage_space_id"]),
            bucket=self._bucket,
            relative_key=task["source_object_key"],
            storage_namespace=task.get("source_storage_namespace"),
        )
        source_body = await self._storage.get(target, max_bytes=self._max_source_bytes)
        if source_body is None:
            return "skipped", "source_deleted_before_fetch"
        source_sha256 = hashlib.sha256(source_body).hexdigest()
        try:
            if not await self._store.resolve_source_sha256(tenant_id, task_id, source_sha256):
                return "skipped", "duplicate_content"
        except SourceChecksumMismatch:
            return "skipped", "source_checksum_mismatch"
        task["source_sha256"] = source_sha256
        await self._store.set_task_phase(tenant_id, task_id, "parsing")
        try:
            extracted = extract_text(
                source_body,
                filename=task["source_object_key"],
                content_type=task["source_content_type"],
                max_characters=self._max_extracted_characters,
            )
            chunks = chunk_segments(extracted.segments, max_characters=self._chunk_characters)
        except (UnsupportedDocumentType, OcrRequiredDocument, ExtractionLimitExceeded) as error:
            return "skipped", str(error)
        if not chunks:
            return "skipped", "source_contains_no_extractable_text"
        await self._store.set_task_phase(tenant_id, task_id, "extracting")
        source_id = f"source::{source_sha256[:16]}"
        llm_result = await self._llm.extract(
            assemble_prompt(contract=self._contract, chunks=chunks, source_id=source_id)
        )
        await self._store.set_task_phase(tenant_id, task_id, "validating")
        drafts = tuple(
            validate_draft(candidate, contract=self._contract, source_id=source_id)
            for candidate in llm_result.cards
        )
        await self._store.set_task_phase(tenant_id, task_id, "writing_cards")
        batch_result = await self._writer.write(
            task=task,
            source_body=source_body,
            drafts=drafts,
            contract=self._contract,
        )
        await self._store.complete_s3_batch(tenant_id, task_id, batch_result)
        return "completed", None
