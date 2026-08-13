"""Durable PostgreSQL-backed executor for queued object operations."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from s3mp.authorization.domain.evaluator import Decision, evaluate
from s3mp.files.application.file_service import FileAuthorizationStore, ObjectStorage, StorageSpaceStore
from s3mp.files.application.delayed_subject_validator import validate_delayed_subject
from s3mp.identity.domain.context import PrincipalContext
from s3mp.storage.domain.policy import derive_provider_target


class OperationStore(Protocol):
    async def claim_operations(self, worker_id: str, limit: int = 10) -> list[dict[str, Any]]: ...
    async def finish_operation(
        self, tenant_id: UUID, operation_id: UUID, status: str, reason: str | None = None
    ) -> None: ...
    async def renew_operation_lease(
        self, tenant_id: UUID, operation_id: UUID, worker_id: str
    ) -> bool: ...


class PrincipalStore(Protocol):
    async def get_principal(self, tenant_id: UUID, principal_id: UUID) -> dict[str, Any] | None: ...
    async def get_membership_state(self, tenant_id: UUID, membership_id: UUID) -> dict[str, Any] | None: ...


class ApiKeyStateStore(Protocol):
    async def get_key_state(self, tenant_id: UUID, key_id: UUID) -> dict[str, Any] | None: ...


@dataclass(slots=True)
class FileOperationWorker:
    store: OperationStore
    storage_store: StorageSpaceStore
    authorization_store: FileAuthorizationStore
    principal_store: PrincipalStore
    object_storage: ObjectStorage
    api_key_state_store: ApiKeyStateStore | None = None

    async def run_once(self, worker_id: str, limit: int = 10) -> list[str]:
        completed: list[str] = []
        for operation in await self.store.claim_operations(worker_id, limit):
            heartbeat = asyncio.create_task(self._heartbeat(operation, worker_id))
            try:
                status, reason = await self._execute(operation)
            finally:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
            await self.store.finish_operation(
                UUID(operation["tenant_id"]), UUID(operation["id"]), status, reason
            )
            completed.append(operation["id"])
        return completed

    async def _heartbeat(self, operation: dict[str, Any], worker_id: str) -> None:
        """Keep a long-running provider operation exclusively leased."""
        tenant_id, operation_id = UUID(operation["tenant_id"]), UUID(operation["id"])
        while True:
            await asyncio.sleep(20)
            if not await self.store.renew_operation_lease(tenant_id, operation_id, worker_id):
                return

    async def _execute(self, operation: dict[str, Any]) -> tuple[str, str | None]:
        tenant_id = UUID(operation["tenant_id"])
        principal_id = UUID(operation["principal_id"])
        space_id = operation.get("storage_space_id")
        if space_id is None:
            return "cancelled", "legacy_operation_missing_storage_space"
        evidence = operation.get("authorization_evidence") or {}
        subject = await validate_delayed_subject(
            principal_store=self.principal_store, api_key_store=self.api_key_state_store,
            tenant_id=tenant_id, principal_id=principal_id, membership_id=operation.get("membership_id"),
            authorization_version=int(operation.get("authorization_version", 0)), evidence=evidence,
        )
        if subject is None:
            return "cancelled", "subject_inactive_or_stale"
        scopes = subject.api_key_scopes or frozenset()
        ctx = PrincipalContext.for_application(
            tenant_id, principal_id, int(operation.get("authorization_version", 1)),
            application_id=UUID(evidence["application_id"]) if evidence.get("application_id") else None,
            api_key_id=UUID(evidence["api_key_id"]) if evidence.get("api_key_id") else None,
            api_key_scopes=scopes,
        ) if subject.subject_kind == "application" else PrincipalContext(
            tenant_id, principal_id,
            UUID(str(operation["membership_id"])) if operation.get("membership_id") else UUID(int=1),
            int(operation.get("authorization_version", 1)),
        )
        space = await self.storage_store.get_space(tenant_id, UUID(space_id))
        if space is None:
            return "cancelled", "storage_space_missing"
        if int(operation.get("provider_target_version", 0)) != int(space.get("provider_target_version", 1)):
            return "cancelled", "legacy_provider_target"

        def target(key: str):
            try:
                return derive_provider_target(
                    tenant_id=tenant_id,
                    storage_space_id=UUID(space_id),
                    bucket=str(space["bucket"]),
                    relative_key=key,
                    operator_prefix=str(space.get("root_prefix") or ""),
                    version=int(space.get("provider_target_version", 1)),
                )
            except (KeyError, ValueError):
                return None

        async def authorize(permission: str, key: str) -> bool:
            if ctx.subject_kind == "application" and permission not in (ctx.api_key_scopes or frozenset()):
                return False
            bindings = await self.authorization_store.bindings_for(
                tenant_id, principal_id, UUID(space_id), subject_kind=ctx.subject_kind
            )
            return evaluate(
                permission, bindings, storage_space_id=UUID(space_id), object_key=key
            ).decision == Decision.ALLOW

        source = operation.get("source_key")
        destination = operation.get("destination_key")
        try:
            if operation["operation_type"] in {"copy", "move"}:
                if not source or not destination:
                    return "failed", "operation_keys_missing"
                if not await authorize("files.read", source) or not await authorize("files.write", destination):
                    return "cancelled", "authorization_revoked"
                source_target, destination_target = target(source), target(destination)
                if source_target is None or destination_target is None:
                    return "cancelled", "storage_target_unverifiable"
                source_state = await self.object_storage.head(source_target)
                destination_state = await self.object_storage.head(destination_target)
                # A previous attempt may have completed the provider effect and
                # crashed before committing its database result.
                if destination_state is None:
                    if source_state is None:
                        return "failed", "source_object_missing"
                    await self.object_storage.copy(source_target, destination_target)
                    destination_state = await self.object_storage.head(destination_target)
                    if destination_state is None:
                        return "retry_wait", "copy_verification_failed"
                if operation["operation_type"] == "move":
                    if source_state is None:
                        return "succeeded", None
                    if not await authorize("files.delete", source):
                        return "partial_failure", "source_delete_authorization_revoked"
                    try:
                        await self.object_storage.delete(source_target)
                    except Exception:
                        return "partial_failure", "source_delete_failed"
            elif operation["operation_type"] == "delete":
                for key in operation.get("keys") or ():
                    if not await authorize("files.delete", key):
                        return "cancelled", "authorization_revoked"
                    key_target = target(key)
                    if key_target is None:
                        return "cancelled", "storage_target_unverifiable"
                    await self.object_storage.delete(key_target)
            else:
                return "failed", "unsupported_operation"
        except Exception:
            return "retry_wait", "object_storage_unavailable"
        return "succeeded", None
