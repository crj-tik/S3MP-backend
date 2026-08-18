"""File, upload, presigned download, and multipart application service."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID

from s3mp.authorization.domain.evaluator import Binding, Decision, evaluate
from s3mp.common.errors import ApiError
from s3mp.common.middleware import current_request_id
from s3mp.files.application.auth_guard import FileAuthGuard
from s3mp.files.application.authorized_command import AuthorizedFileCommand
from s3mp.files.application.delayed_subject_validator import validate_delayed_subject
from s3mp.files.domain.file_status import FileObjectStatus
from s3mp.files.domain.ingestion import IngestionStatus
from s3mp.identity.domain.context import PrincipalContext
from s3mp.storage.domain.policy import ProviderTarget, derive_provider_target

MULTIPART_PART_SIZE = 8 * 1024 * 1024


class FileStore(Protocol):
    async def list_files(
        self,
        tenant_id: UUID,
        space_id: UUID,
        prefix: str,
        status: FileObjectStatus = FileObjectStatus.AVAILABLE,
    ) -> list[dict[str, Any]]: ...
    async def get_file(
        self, tenant_id: UUID, space_id: UUID, file_id: UUID
    ) -> dict[str, Any] | None: ...
    async def delete_file(
        self, tenant_id: UUID, space_id: UUID, file_id: UUID, **data: Any
    ) -> None: ...
    async def list_pending_deletions(self) -> list[dict[str, Any]]: ...
    async def finalize_file_delete(self, tenant_id: UUID, file_id: UUID) -> None: ...
    async def record_delete_failure(
        self, tenant_id: UUID, file_id: UUID, max_attempts: int
    ) -> None: ...
    async def create_operation(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def get_operation(self, tenant_id: UUID, op_id: UUID) -> dict[str, Any] | None: ...
    async def create_upload(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def get_upload(self, tenant_id: UUID, upload_id: UUID) -> dict[str, Any] | None: ...
    async def expire_upload(self, tenant_id: UUID, upload_id: UUID) -> None: ...
    async def complete_upload(
        self, tenant_id: UUID, upload_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def create_multipart(
        self, tenant_id: UUID, space_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def set_multipart_provider_id(
        self, tenant_id: UUID, multipart_id: UUID, provider_upload_id: str
    ) -> dict[str, Any]: ...
    async def get_multipart(self, tenant_id: UUID, multipart_id: UUID) -> dict[str, Any] | None: ...
    async def expire_multipart(self, tenant_id: UUID, multipart_id: UUID) -> None: ...
    async def abort_multipart(
        self, tenant_id: UUID, multipart_id: UUID, *, idempotency_key: str | None = None
    ) -> None: ...
    async def list_multipart_parts(
        self, tenant_id: UUID, multipart_id: UUID
    ) -> list[dict[str, Any]]: ...
    async def record_multipart_part(
        self, tenant_id: UUID, multipart_id: UUID, part_number: int, data: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def complete_multipart(
        self, tenant_id: UUID, multipart_id: UUID, data: dict[str, Any]
    ) -> dict[str, Any]: ...


class StorageSpaceStore(Protocol):
    async def get_space(self, tenant_id: UUID, space_id: UUID) -> dict[str, Any] | None: ...


class FileAuthorizationStore(Protocol):
    async def bindings_for(
        self,
        tenant_id: UUID,
        principal_id: UUID,
        storage_space_id: UUID,
        *,
        subject_kind: str = "human",
    ) -> list[Binding]: ...


class PrincipalStateStore(Protocol):
    async def get_principal(self, tenant_id: UUID, principal_id: UUID) -> dict[str, Any] | None: ...
    async def get_membership_state(
        self, tenant_id: UUID, membership_id: UUID
    ) -> dict[str, Any] | None: ...


class ApiKeyStateStore(Protocol):
    async def get_key_state(self, tenant_id: UUID, key_id: UUID) -> dict[str, Any] | None: ...


class WorkNotifier(Protocol):
    async def notify(self) -> bool: ...


class IngestionStore(Protocol):
    async def create_upload_intent(
        self, tenant_id: UUID, session_data: dict[str, Any], ingestion_data: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def create_multipart_intent(
        self, tenant_id: UUID, session_data: dict[str, Any], ingestion_data: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def begin_or_replay(self, tenant_id: UUID, data: dict[str, Any]) -> dict[str, Any]: ...
    async def get_record(self, tenant_id: UUID, ingestion_id: UUID) -> dict[str, Any] | None: ...
    async def get_provenance(
        self, tenant_id: UUID, ingestion_id: UUID
    ) -> dict[str, Any] | None: ...
    async def get_for_session(
        self,
        tenant_id: UUID,
        *,
        upload_session_id: UUID | None = None,
        multipart_session_id: UUID | None = None,
    ) -> dict[str, Any] | None: ...
    async def record_provider_result(
        self,
        tenant_id: UUID,
        ingestion_id: UUID,
        *,
        provider_etag: str | None = None,
        provider_version_id: str | None = None,
        actual_size: int | None = None,
        actual_content_type: str | None = None,
        checksum: str | None = None,
    ) -> dict[str, Any]: ...
    async def commit_verified_file(self, tenant_id: UUID, ingestion_id: UUID) -> dict[str, Any]: ...
    async def fail_or_quarantine(
        self,
        tenant_id: UUID,
        ingestion_id: UUID,
        status: IngestionStatus,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    async def expire(self, tenant_id: UUID, ingestion_id: UUID) -> dict[str, Any]: ...
    async def list_pending(self, tenant_id: UUID | None = None) -> list[dict[str, Any]]: ...
    async def reconciliation_attempt_count(self, tenant_id: UUID, ingestion_id: UUID) -> int: ...

    async def reap_orphan_reservations(
        self, tenant_id: UUID | None = None, limit: int = 100
    ) -> list[str]: ...


class ObjectMetadata(Protocol):
    @property
    def content_length(self) -> int: ...

    @property
    def content_type(self) -> str | None: ...

    @property
    def etag(self) -> str | None: ...

    @property
    def version_id(self) -> str | None: ...


class ObjectStorage(Protocol):
    async def put(
        self, target: ProviderTarget, body: bytes, content_type: str
    ) -> ObjectMetadata: ...
    async def head(self, target: ProviderTarget) -> ObjectMetadata | None: ...
    async def delete(self, target: ProviderTarget) -> None: ...

    async def list_objects(
        self,
        prefix: str = "",
        *,
        continuation_token: str | None = None,
        max_keys: int = 1000,
    ) -> tuple[list[Any], str | None]: ...
    async def copy(self, source: ProviderTarget, destination: ProviderTarget) -> ObjectMetadata: ...
    async def presign_get(self, target: ProviderTarget, expires_in: int) -> str: ...
    async def presign_put(
        self, target: ProviderTarget, content_type: str, expires_in: int
    ) -> str: ...
    async def readiness_probe(self) -> None: ...
    # ── Multipart ──────────────────────────────────────────────────────────
    async def create_multipart_upload(self, target: ProviderTarget, content_type: str) -> str: ...
    async def upload_part(
        self, target: ProviderTarget, upload_id: str, part_number: int, body: bytes
    ) -> dict[str, object]: ...
    async def complete_multipart_upload(
        self, target: ProviderTarget, upload_id: str, parts: list[dict[str, object]]
    ) -> ObjectMetadata: ...
    async def abort_multipart_upload(self, target: ProviderTarget, upload_id: str) -> None: ...
    async def list_parts(
        self, target: ProviderTarget, upload_id: str
    ) -> list[dict[str, object]]: ...


@dataclass
class FileApplicationService:
    store: FileStore
    object_storage: ObjectStorage | None = None
    storage_store: StorageSpaceStore | None = None
    authorization_store: FileAuthorizationStore | None = None
    ingestion_store: IngestionStore | None = None
    principal_store: PrincipalStateStore | None = None
    api_key_state_store: ApiKeyStateStore | None = None
    work_notifier: WorkNotifier | None = None
    reconciliation_max_attempts: int = 5

    async def _resolve_space(self, tenant_id: UUID, space_id: UUID) -> dict[str, Any]:
        """Resolve storage space and validate tenant ownership."""
        if self.storage_store is None:
            raise ApiError("internal_error", "Storage store not configured", status_code=500)
        space = await self.storage_store.get_space(tenant_id, space_id)
        if space is None:
            raise ApiError("resource_not_found", "Storage space not found", status_code=404)
        return space

    def _physical_key(self, space: dict[str, Any], relative_key: str) -> str:
        """Build the server-owned provider key for a relative object key."""
        return derive_provider_target(
            tenant_id=UUID(str(space["tenant_id"])),
            storage_space_id=UUID(str(space["id"])),
            bucket=str(space["bucket"]),
            relative_key=relative_key,
            operator_prefix=str(space.get("root_prefix") or ""),
            storage_namespace=(
                str(space["storage_namespace"]) if space.get("storage_namespace") else None
            ),
            version=int(space.get("provider_target_version", 1)),
        ).key

    def _relative_key(self, space: dict[str, Any], physical_key: str) -> str:
        expected = self._physical_key(space, "")
        prefix = expected + "/"
        if not physical_key.startswith(prefix):
            raise ApiError(
                "resource_not_found", "Provider target is not in the storage space", status_code=404
            )
        return physical_key[len(prefix) :]

    @staticmethod
    def _target(bucket: str, physical_key: str) -> ProviderTarget:
        return ProviderTarget(bucket=str(bucket), key=str(physical_key))

    def _public_upload(self, space: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        public = dict(record)
        public["object_key"] = self._relative_key(space, str(record["object_key"]))
        public.pop("tenant_id", None)
        public.pop("provider_target_version", None)
        public.pop("membership_id", None)
        return public

    async def _public_direct_upload(
        self, space: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any]:
        if record.get("status") != "pending":
            public = self._public_upload(space, record)
            public.update({"mode": "direct", "method": "PUT", "url": None, "headers": {}})
            return public
        if self.object_storage is None:
            raise ApiError(
                "storage_capability_unsupported",
                "Object storage is not configured",
                status_code=422,
            )
        expires_at = datetime.fromisoformat(str(record["expires_at"]).replace("Z", "+00:00"))
        ttl = min(900, int((expires_at - datetime.now(UTC)).total_seconds()))
        if ttl < 30:
            raise ApiError("resource_expired", "Upload session has expired", status_code=410)
        target = ProviderTarget(bucket=str(space["bucket"]), key=str(record["object_key"]))
        url = await self.object_storage.presign_put(target, str(record["content_type"]), ttl)
        public = self._public_upload(space, record)
        public.update(
            {
                "mode": "direct",
                "method": "PUT",
                "url": url,
                "headers": {"Content-Type": str(record["content_type"])},
            }
        )
        return public

    def _public_file(self, space: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        """Project an internal file record into the external API representation."""
        public = dict(record)
        public["object_key"] = self._relative_key(space, str(record["object_key"]))
        for field in (
            "tenant_id",
            "provider_target_version",
            "deletion_principal_id",
            "deletion_authorization_version",
            "deletion_authorization_evidence",
        ):
            public.pop(field, None)
        return public

    def _public_multipart(self, space: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        public = self._public_upload(space, record)
        # Provider upload ids are capabilities, not API resource identifiers.
        public.pop("provider_upload_id", None)
        public["mode"] = "multipart"
        public["part_size"] = MULTIPART_PART_SIZE
        return public

    @staticmethod
    def _public_operation(record: dict[str, Any]) -> dict[str, Any]:
        public = dict(record)
        for field in (
            "tenant_id",
            "principal_id",
            "membership_id",
            "storage_space_id",
            "provider_target_version",
            "authorization_version",
            "authorization_evidence",
            "lease_owner",
            "lease_expires_at",
        ):
            public.pop(field, None)
        return public

    @staticmethod
    def _public_ingestion_result(record: dict[str, Any]) -> dict[str, Any]:
        """Redact reconciliation-only fields from a completed upload response."""
        public = dict(record)
        for field in (
            "tenant_id",
            "creator_principal_id",
            "acting_principal_id",
            "membership_id",
            "storage_space_id",
            "bucket",
            "relative_key",
            "physical_key",
            "provider_target_version",
            "authorization_evidence",
            "authorization_version",
            "request_id",
            "idempotency_fingerprint",
        ):
            public.pop(field, None)
        return public

    async def _command(
        self,
        ctx: PrincipalContext,
        space_id: str,
        relative_key: str,
        action: str,
        *,
        idempotency_key: str | None = None,
        semantics: dict[str, Any] | None = None,
    ) -> AuthorizedFileCommand:
        space = await self._resolve_space(ctx.tenant_id, UUID(space_id))
        if self.authorization_store is None:
            raise ApiError(
                "internal_error", "File authorization store is not configured", status_code=500
            )
        bindings = await self.authorization_store.bindings_for(
            ctx.tenant_id, ctx.principal_id, UUID(space_id), subject_kind=ctx.subject_kind
        )
        return AuthorizedFileCommand.create(
            ctx,
            space,
            relative_key,
            action,
            bindings,
            request_id=current_request_id(),
            idempotency_key=idempotency_key or "",
            semantics=semantics,
        )

    async def _command_for_record(
        self,
        ctx: PrincipalContext,
        record: dict[str, Any],
        action: str,
        *,
        idempotency_key: str | None = None,
        semantics: dict[str, Any] | None = None,
    ) -> AuthorizedFileCommand:
        space_id = record["storage_space_id"]
        space = await self._resolve_space(ctx.tenant_id, UUID(space_id))
        if int(record.get("provider_target_version", 0)) != int(
            space.get("provider_target_version", 1)
        ):
            raise ApiError(
                "resource_not_found", "Provider target requires migration", status_code=404
            )
        physical_key = str(record["object_key"])
        relative_key = self._relative_key(space, physical_key)
        return await self._command(
            ctx,
            space_id,
            relative_key,
            action,
            idempotency_key=idempotency_key,
            semantics=semantics,
        )

    async def _begin_ingestion(
        self,
        command: AuthorizedFileCommand,
        *,
        upload_session_id: str | None = None,
        multipart_session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any] | None:
        if self.ingestion_store is None:
            return None
        return await self.ingestion_store.begin_or_replay(
            command.tenant_id,
            {
                "creator_principal_id": str(command.acting_principal_id),
                "acting_principal_id": str(command.acting_principal_id),
                "membership_id": str(command.authorization_evidence.get("membership_id"))
                if command.authorization_evidence.get("membership_id")
                else None,
                "storage_space_id": str(command.storage_space_id),
                "bucket": command.bucket,
                "relative_key": command.relative_key,
                "physical_key": command.physical_key,
                "provider_target_version": command.provider_target_version,
                "authorization_evidence": command.authorization_evidence,
                "authorization_version": command.authorization_version,
                "request_id": command.request_id,
                "idempotency_key": idempotency_key,
                "idempotency_fingerprint": command.idempotency_fingerprint or None,
                "upload_session_id": upload_session_id,
                "multipart_session_id": multipart_session_id,
            },
        )

    async def _ingestion_for_session(
        self, tenant_id: UUID, *, upload_id: str | None = None, multipart_id: str | None = None
    ) -> dict[str, Any] | None:
        if self.ingestion_store is None:
            return None
        if upload_id is not None:
            return await self.ingestion_store.get_for_session(
                tenant_id, upload_session_id=UUID(upload_id)
            )
        return await self.ingestion_store.get_for_session(
            tenant_id, multipart_session_id=UUID(multipart_id or "")
        )

    @staticmethod
    def _is_expired(record: dict[str, Any]) -> bool:
        raw = record.get("expires_at")
        if not raw:
            return False
        expires_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return expires_at <= datetime.now(UTC)

    async def _ensure_upload_active(self, record: dict[str, Any]) -> None:
        if self._is_expired(record) and record.get("status") == "pending":
            await self.store.expire_upload(UUID(record["tenant_id"]), UUID(record["id"]))
            ingestion = await self._ingestion_for_session(
                UUID(record["tenant_id"]), upload_id=record["id"]
            )
            if ingestion is not None:
                await self.ingestion_store.expire(UUID(record["tenant_id"]), UUID(ingestion["id"]))  # type: ignore[union-attr]
            raise ApiError("resource_expired", "Upload session has expired", status_code=410)

    async def _ensure_multipart_active(self, record: dict[str, Any]) -> None:
        if not self._is_expired(record) or record.get("status") != "pending":
            return
        provider_upload_id = record.get("provider_upload_id")
        if self.object_storage is not None and provider_upload_id:
            try:
                space = await self._resolve_space(
                    UUID(record["tenant_id"]), UUID(record["storage_space_id"])
                )
                if int(record.get("provider_target_version", 0)) != int(
                    space.get("provider_target_version", 1)
                ):
                    raise ApiError(
                        "resource_not_found", "Provider target requires migration", status_code=404
                    )
                self._relative_key(space, str(record["object_key"]))
                await self.object_storage.abort_multipart_upload(
                    self._target(space["bucket"], record["object_key"]), provider_upload_id
                )
            except Exception as exc:
                raise ApiError(
                    "storage_unavailable",
                    "Expired multipart cleanup requires retry",
                    status_code=503,
                ) from exc
        await self.store.expire_multipart(UUID(record["tenant_id"]), UUID(record["id"]))
        ingestion = await self._ingestion_for_session(
            UUID(record["tenant_id"]), multipart_id=record["id"]
        )
        if ingestion is not None:
            await self.ingestion_store.expire(UUID(record["tenant_id"]), UUID(ingestion["id"]))  # type: ignore[union-attr]
        raise ApiError("resource_expired", "Multipart upload has expired", status_code=410)

    def _ingestion_data(
        self, command: AuthorizedFileCommand, idempotency_key: str | None
    ) -> dict[str, Any]:
        return {
            "creator_principal_id": str(command.acting_principal_id),
            "acting_principal_id": str(command.acting_principal_id),
            "membership_id": str(command.authorization_evidence.get("membership_id"))
            if command.authorization_evidence.get("membership_id")
            else None,
            "storage_space_id": str(command.storage_space_id),
            "bucket": command.bucket,
            "relative_key": command.relative_key,
            "physical_key": command.physical_key,
            "provider_target_version": command.provider_target_version,
            "authorization_evidence": command.authorization_evidence,
            "authorization_version": command.authorization_version,
            "request_id": command.request_id,
            "idempotency_key": idempotency_key,
            "idempotency_fingerprint": command.idempotency_fingerprint or None,
        }

    async def reconcile_pending_ingestions(self) -> list[dict[str, Any]]:
        """Re-verify durable pending intents after provider/DB partial failure.

        This is an internal worker entry point, not a public HTTP operation:
        it relies on the persisted authorization evidence recorded before the
        provider call and never accepts a caller-supplied object key.
        """
        if self.ingestion_store is None or self.object_storage is None:
            return []
        reconciled: list[dict[str, Any]] = []
        for record in await self.ingestion_store.list_pending():
            if record["status"] == IngestionStatus.INITIATED.value:
                continue
            ingestion_id = UUID(record["id"])
            try:
                attempts = await self.ingestion_store.reconciliation_attempt_count(
                    UUID(record["tenant_id"]), ingestion_id
                )
                if attempts >= self.reconciliation_max_attempts:
                    await self.ingestion_store.fail_or_quarantine(
                        UUID(record["tenant_id"]),
                        ingestion_id,
                        IngestionStatus.FAILED,
                        "reconciliation_retry_exhausted",
                    )
                    continue
                if not await self._revalidate_ingestion(record):
                    await self.ingestion_store.fail_or_quarantine(
                        UUID(record["tenant_id"]),
                        ingestion_id,
                        IngestionStatus.FAILED,
                        "reconciliation_authorization_revoked",
                    )
                    continue
                space = await self._resolve_space(
                    UUID(record["tenant_id"]), UUID(record["storage_space_id"])
                )
                if int(record.get("provider_target_version", 0)) != int(
                    space.get("provider_target_version", 1)
                ):
                    await self.ingestion_store.fail_or_quarantine(
                        UUID(record["tenant_id"]),
                        ingestion_id,
                        IngestionStatus.RECONCILIATION_REQUIRED,
                        "legacy_provider_target",
                    )
                    continue
                if str(record["bucket"]) != str(space["bucket"]) or str(
                    record["physical_key"]
                ) != self._physical_key(space, str(record["relative_key"])):
                    await self.ingestion_store.fail_or_quarantine(
                        UUID(record["tenant_id"]),
                        ingestion_id,
                        IngestionStatus.RECONCILIATION_REQUIRED,
                        "provider_target_mismatch",
                    )
                    continue
                if record["status"] == IngestionStatus.VERIFIED.value:
                    reconciled.append(
                        await self.ingestion_store.commit_verified_file(
                            UUID(record["tenant_id"]), ingestion_id
                        )
                    )
                    continue
                metadata = await self.object_storage.head(
                    self._target(record["bucket"], record["physical_key"])
                )
                if metadata is None:
                    await self.ingestion_store.fail_or_quarantine(
                        UUID(record["tenant_id"]),
                        ingestion_id,
                        IngestionStatus.FAILED,
                        "reconciliation_object_missing",
                    )
                    continue
                await self.ingestion_store.record_provider_result(
                    UUID(record["tenant_id"]),
                    ingestion_id,
                    provider_etag=getattr(metadata, "etag", None),
                    provider_version_id=getattr(metadata, "version_id", None),
                    actual_size=metadata.content_length,
                    actual_content_type=metadata.content_type,
                    checksum=record.get("checksum"),
                )
                reconciled.append(
                    await self.ingestion_store.commit_verified_file(
                        UUID(record["tenant_id"]), ingestion_id
                    )
                )
            except ApiError:
                raise
            except Exception:
                await self.ingestion_store.fail_or_quarantine(
                    UUID(record["tenant_id"]),
                    ingestion_id,
                    IngestionStatus.RECONCILIATION_REQUIRED,
                    "reconciliation_retry_required",
                )
        return reconciled

    async def _revalidate_ingestion(self, record: dict[str, Any]) -> bool:
        if self.authorization_store is None or self.storage_store is None:
            return False
        tenant_id = UUID(record["tenant_id"])
        space = await self.storage_store.get_space(tenant_id, UUID(record["storage_space_id"]))
        if space is None:
            return False
        if (
            (
                record.get("application_id")
                and str(record["application_id"]) != str(space.get("application_id"))
            )
            or (
                record.get("storage_namespace")
                and record["storage_namespace"] != space.get("storage_namespace")
            )
            or int(record.get("profile_version", 1)) != int(space.get("profile_version", 1))
        ):
            return False
        principal_id = UUID(record["acting_principal_id"])
        evidence = record.get("authorization_evidence") or {}
        subject = await validate_delayed_subject(
            principal_store=self.principal_store,
            api_key_store=self.api_key_state_store,
            tenant_id=tenant_id,
            principal_id=principal_id,
            membership_id=record.get("membership_id"),
            authorization_version=int(record["authorization_version"]),
            evidence=evidence,
            required_permission="files.write",
        )
        if subject is None:
            return False
        bindings = await self.authorization_store.bindings_for(
            tenant_id,
            principal_id,
            UUID(record["storage_space_id"]),
            subject_kind=subject.subject_kind,
        )
        return (
            evaluate("files.write", bindings, object_key=record["relative_key"]).decision
            == Decision.ALLOW
        )

    async def reconcile_pending_deletions(self) -> list[str]:
        """Finish durable delete intents after the provider operation succeeds."""
        if self.object_storage is None:
            return []
        finalized: list[str] = []
        for record in await self.store.list_pending_deletions():
            try:
                evidence = record.get("deletion_authorization_evidence") or {}
                principal_id = record.get("deletion_principal_id")
                if not principal_id or not await self._revalidate_delayed_action(
                    UUID(record["tenant_id"]),
                    UUID(principal_id),
                    UUID(record["storage_space_id"]),
                    record["object_key"],
                    "files.delete",
                    int(record.get("deletion_authorization_version") or 1),
                    evidence,
                ):
                    await self.store.record_delete_failure(
                        UUID(record["tenant_id"]), UUID(record["id"]), 1
                    )
                    continue
                space = await self._resolve_space(
                    UUID(record["tenant_id"]), UUID(record["storage_space_id"])
                )
                if int(record.get("provider_target_version", 0)) != int(
                    space.get("provider_target_version", 1)
                ):
                    await self.store.record_delete_failure(
                        UUID(record["tenant_id"]),
                        UUID(record["id"]),
                        self.reconciliation_max_attempts,
                    )
                    continue
                if (
                    (
                        record.get("application_id")
                        and str(record["application_id"]) != str(space.get("application_id"))
                    )
                    or (
                        record.get("storage_namespace")
                        and record["storage_namespace"] != space.get("storage_namespace")
                    )
                    or int(record.get("profile_version", 1)) != int(space.get("profile_version", 1))
                ):
                    await self.store.record_delete_failure(
                        UUID(record["tenant_id"]),
                        UUID(record["id"]),
                        self.reconciliation_max_attempts,
                    )
                    continue
                self._relative_key(space, str(record["object_key"]))
                await self.object_storage.delete(
                    self._target(space["bucket"], record["object_key"])
                )
                await self.store.finalize_file_delete(UUID(record["tenant_id"]), UUID(record["id"]))
                finalized.append(record["id"])
            except Exception:
                await self.store.record_delete_failure(
                    UUID(record["tenant_id"]), UUID(record["id"]), self.reconciliation_max_attempts
                )
        return finalized

    async def _revalidate_delayed_action(
        self,
        tenant_id: UUID,
        principal_id: UUID,
        space_id: UUID,
        relative_key: str,
        permission: str,
        authorization_version: int,
        evidence: dict[str, Any],
    ) -> bool:
        if self.authorization_store is None:
            return False
        subject = await validate_delayed_subject(
            principal_store=self.principal_store,
            api_key_store=self.api_key_state_store,
            tenant_id=tenant_id,
            principal_id=principal_id,
            membership_id=evidence.get("membership_id"),
            authorization_version=authorization_version,
            evidence=evidence,
            required_permission=permission,
        )
        if subject is None:
            return False
        bindings = await self.authorization_store.bindings_for(
            tenant_id, principal_id, space_id, subject_kind=subject.subject_kind
        )
        return (
            evaluate(
                permission, bindings, storage_space_id=space_id, object_key=relative_key
            ).decision
            == Decision.ALLOW
        )

    # ── Files ──────────────────────────────────────────────────────────────

    async def list_files(
        self,
        ctx: PrincipalContext,
        space_id: str,
        prefix: str,
        status: FileObjectStatus = FileObjectStatus.AVAILABLE,
    ) -> list[dict[str, Any]]:
        command = await self._command(ctx, space_id, prefix, "files.list")
        space = await self._resolve_space(ctx.tenant_id, command.storage_space_id)
        return [
            self._public_file(space, record)
            for record in await self.store.list_files(
                ctx.tenant_id, command.storage_space_id, command.physical_key, status
            )
        ]

    async def get_ingestion_provenance(
        self, ctx: PrincipalContext, ingestion_id: str
    ) -> dict[str, Any]:
        if self.ingestion_store is None:
            raise ApiError("internal_error", "Ingestion store not configured", status_code=500)
        try:
            identifier = UUID(ingestion_id)
        except ValueError as exc:
            raise ApiError(
                "resource_not_found", "Ingestion record not found", status_code=404
            ) from exc
        chain = await self.ingestion_store.get_provenance(ctx.tenant_id, identifier)
        if chain is None:
            raise ApiError("resource_not_found", "Ingestion record not found", status_code=404)
        ingestion = chain["ingestion"]
        await self._command(
            ctx,
            str(ingestion["storage_space_id"]),
            str(ingestion["relative_key"]),
            "files.read",
        )
        return chain

    async def get_file(self, ctx: PrincipalContext, space_id: str, file_id: str) -> dict[str, Any]:
        result = await self.store.get_file(ctx.tenant_id, UUID(space_id), UUID(file_id))
        if result is None:
            raise ApiError("resource_not_found", "File not found", status_code=404)
        await self._command_for_record(ctx, result, "files.read")
        return self._public_file(await self._resolve_space(ctx.tenant_id, UUID(space_id)), result)

    async def delete_file(
        self,
        ctx: PrincipalContext,
        space_id: str,
        file_id: str,
        idempotency_key: str | None = None,
        if_match: str | None = None,
    ) -> dict[str, Any]:
        record = await self.store.get_file(ctx.tenant_id, UUID(space_id), UUID(file_id))
        if record is None:
            raise ApiError("resource_not_found", "File not found", status_code=404)
        command = await self._command_for_record(
            ctx,
            record,
            "files.delete",
            idempotency_key=idempotency_key,
            semantics={"if_match": if_match},
        )
        # The repository validates If-Match and durably records a deleting
        # intent before a worker is ever allowed to touch MinIO.
        if if_match is None:
            from s3mp.common.api.etag import require_if_match

            require_if_match(None)
        if record.get("etag") != if_match:
            from s3mp.common.api.etag import check_etag

            check_etag(record.get("etag") or "", require_if_match(if_match))
        await self.store.delete_file(
            ctx.tenant_id,
            UUID(space_id),
            UUID(file_id),
            idempotency_key=idempotency_key,
            if_match=if_match,
            actor_principal_id=ctx.principal_id,
            request_id=current_request_id(),
            object_key=record["object_key"],
            authorization_version=ctx.authorization_version,
            authorization_evidence=command.authorization_evidence,
        )
        if self.work_notifier is not None:
            await self.work_notifier.notify()
        return {"status": "deletion_queued"}

    async def create_file_operation(
        self,
        ctx: PrincipalContext,
        space_id: str,
        body: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        operation_actions = {
            "copy": (("files.read", body.source_key), ("files.write", body.destination_key)),
            "move": (
                ("files.read", body.source_key),
                ("files.delete", body.source_key),
                ("files.write", body.destination_key),
            ),
        }
        commands: list[AuthorizedFileCommand] = []
        if body.operation_type in operation_actions:
            for action, key in operation_actions[body.operation_type]:
                if not key:
                    raise ApiError(
                        "validation_failed", "Operation key is required", status_code=422
                    )
                commands.append(
                    await self._command(
                        ctx,
                        space_id,
                        key,
                        action,
                        idempotency_key=idempotency_key,
                        semantics={"operation_type": body.operation_type},
                    )
                )
        elif body.operation_type == "delete":
            if not body.keys:
                raise ApiError("validation_failed", "At least one key is required", status_code=422)
            for key in body.keys:
                commands.append(
                    await self._command(
                        ctx,
                        space_id,
                        key,
                        "files.delete",
                        idempotency_key=idempotency_key,
                        semantics={
                            "operation_type": body.operation_type,
                            "keys": sorted(body.keys),
                        },
                    )
                )
        else:
            raise ApiError("validation_failed", "Unsupported file operation", status_code=422)
        data = {
            "principal_id": str(ctx.principal_id),
            "membership_id": str(ctx.membership_id) if ctx.membership_id else None,
            "operation_type": body.operation_type,
            "source_key": body.source_key,
            "destination_key": body.destination_key,
            "keys": body.keys,
            "idempotency_key": idempotency_key,
            "authorization_version": ctx.authorization_version,
            "provider_target_version": commands[0].provider_target_version,
            "authorization_evidence": {
                "subject_kind": ctx.subject_kind,
                "application_id": str(ctx.application_id) if ctx.application_id else None,
                "api_key_id": str(ctx.api_key_id) if ctx.api_key_id else None,
                "api_key_scopes": sorted(ctx.api_key_scopes or ()),
                "commands": [command.authorization_evidence for command in commands],
            },
        }
        space = await self._resolve_space(ctx.tenant_id, UUID(space_id))
        data.update(
            {
                "application_id": space.get("application_id"),
                "storage_namespace": space.get("storage_namespace"),
                "profile_version": space.get("profile_version", 1),
            }
        )
        result = await self.store.create_operation(ctx.tenant_id, UUID(space_id), data)
        if self.work_notifier is not None:
            await self.work_notifier.notify()
        return self._public_operation(result)

    async def get_file_operation(self, ctx: PrincipalContext, operation_id: str) -> dict[str, Any]:
        result = await self.store.get_operation(ctx.tenant_id, UUID(operation_id))
        if result is None:
            raise ApiError("resource_not_found", "Operation not found", status_code=404)
        if str(result.get("principal_id")) != str(ctx.principal_id):
            space_id = result.get("storage_space_id")
            if not space_id:
                raise ApiError("resource_not_found", "File operation not found", status_code=404)
            required: list[tuple[str, str]] = []
            operation_type = result.get("operation_type")
            if operation_type in {"copy", "move"}:
                if not result.get("source_key") or not result.get("destination_key"):
                    raise ApiError(
                        "resource_not_found", "File operation not found", status_code=404
                    )
                required = [
                    ("files.read", result["source_key"]),
                    ("files.write", result["destination_key"]),
                ]
                if operation_type == "move":
                    required.append(("files.delete", result["source_key"]))
            elif operation_type == "delete":
                required = [("files.delete", key) for key in result.get("keys") or ()]
            else:
                raise ApiError("resource_not_found", "File operation not found", status_code=404)
            try:
                for permission, key in required:
                    await self._command(ctx, str(space_id), str(key), permission)
            except ApiError as exc:
                if exc.code == "permission_denied":
                    raise ApiError(
                        "permission_denied", "Delegated access is required", status_code=403
                    ) from exc
                raise
        return self._public_operation(result)

    # ── Uploads ────────────────────────────────────────────────────────────

    async def create_direct_upload(
        self,
        ctx: PrincipalContext,
        space_id: str,
        body: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if self.object_storage is None:
            raise ApiError(
                "storage_capability_unsupported",
                "Object storage is not configured",
                status_code=422,
            )
        command = await self._command(
            ctx,
            space_id,
            body.object_key,
            "files.write",
            idempotency_key=idempotency_key,
            semantics={
                "content_length": body.content_length,
                "content_type": body.content_type.lower(),
                "checksum": body.checksum,
            },
        )
        data = {
            "principal_id": str(ctx.principal_id),
            "membership_id": str(ctx.membership_id) if ctx.membership_id else None,
            "object_key": command.physical_key,
            "provider_target_version": command.provider_target_version,
            "content_length": body.content_length,
            "content_type": body.content_type,
            "checksum": body.checksum,
            "idempotency_key": idempotency_key,
        }
        space = await self._resolve_space(ctx.tenant_id, command.storage_space_id)
        data.update(
            {
                "application_id": space.get("application_id"),
                "storage_namespace": space.get("storage_namespace"),
                "profile_version": space.get("profile_version", 1),
            }
        )
        if self.ingestion_store is None:
            record = await self.store.create_upload(ctx.tenant_id, command.storage_space_id, data)
        else:
            record = await self.ingestion_store.create_upload_intent(
                ctx.tenant_id,
                {
                    **data,
                    "storage_space_id": str(command.storage_space_id),
                    "expires_at": datetime.now(UTC) + timedelta(hours=24),
                },
                self._ingestion_data(command, idempotency_key),
            )
            record.pop("replayed", None)
        try:
            return await self._public_direct_upload(
                await self._resolve_space(ctx.tenant_id, command.storage_space_id), record
            )
        except Exception as exc:
            if record.get("status") == "pending":
                await self.store.expire_upload(ctx.tenant_id, UUID(record["id"]))
                ingestion_id = record.get("ingestion_id")
                if ingestion_id is not None and self.ingestion_store is not None:
                    await self.ingestion_store.fail_or_quarantine(
                        ctx.tenant_id,
                        UUID(str(ingestion_id)),
                        IngestionStatus.RECONCILIATION_REQUIRED,
                        "direct_presign_failed",
                    )
            if isinstance(exc, ApiError):
                raise
            raise ApiError(
                "storage_unavailable", "Direct upload preparation failed", status_code=503
            ) from exc

    async def get_direct_upload(self, ctx: PrincipalContext, upload_id: str) -> dict[str, Any]:
        result = await self.store.get_upload(ctx.tenant_id, UUID(upload_id))
        if result is None:
            raise ApiError("resource_not_found", "Upload not found", status_code=404)
        FileAuthGuard.check_ownership(result, ctx)
        await self._command_for_record(ctx, result, "files.write")
        await self._ensure_upload_active(result)
        return await self._public_direct_upload(
            await self._resolve_space(ctx.tenant_id, UUID(result["storage_space_id"])), result
        )

    async def complete_direct_upload(
        self,
        ctx: PrincipalContext,
        upload_id: str,
        body: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        record = await self.store.get_upload(ctx.tenant_id, UUID(upload_id))
        if record is None:
            raise ApiError("resource_not_found", "Upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        command = await self._command_for_record(
            ctx,
            record,
            "files.write",
            idempotency_key=idempotency_key,
            semantics={"checksum": body.checksum},
        )
        await self._ensure_upload_active(record)
        if record.get("status") != "pending":
            raise ApiError("upload_verification_failed", "Upload not pending", status_code=409)
        if self.object_storage is None:
            raise ApiError(
                "storage_capability_unsupported",
                "Object storage is not configured",
                status_code=422,
            )
        ingestion = await self._ingestion_for_session(ctx.tenant_id, upload_id=upload_id)
        try:
            obj = await self.object_storage.head(command.provider_target)
            if obj is None or getattr(obj, "key", command.physical_key) != command.physical_key:
                raise ApiError(
                    "upload_verification_failed", "Object not found in storage", status_code=409
                )
            if getattr(obj, "content_length", None) != record["content_length"]:
                raise ApiError(
                    "upload_verification_failed", "Object size mismatch", status_code=409
                )
            actual_type = getattr(obj, "content_type", None)
            if actual_type and actual_type.lower() != str(record["content_type"]).lower():
                raise ApiError(
                    "upload_verification_failed", "Object content type mismatch", status_code=409
                )
            requested_checksum = body.checksum or record.get("checksum")
            actual_checksum = getattr(obj, "checksum_sha256", None)
            if requested_checksum and requested_checksum not in {
                actual_checksum,
                f"sha256:{actual_checksum}",
            }:
                raise ApiError(
                    "upload_verification_failed", "Object checksum mismatch", status_code=409
                )
        except ApiError:
            if ingestion is not None:
                await self.ingestion_store.fail_or_quarantine(  # type: ignore[union-attr]
                    ctx.tenant_id,
                    UUID(ingestion["id"]),
                    IngestionStatus.FAILED,
                    "provider_verification_failed",
                )
            raise
        except Exception as exc:
            if ingestion is not None:
                await self.ingestion_store.fail_or_quarantine(  # type: ignore[union-attr]
                    ctx.tenant_id,
                    UUID(ingestion["id"]),
                    IngestionStatus.RECONCILIATION_REQUIRED,
                    "provider_unavailable",
                )
            raise ApiError(
                "storage_unavailable", "Object storage verification failed", status_code=503
            ) from exc
        provider_etag = getattr(obj, "etag", None)
        provider_version = getattr(obj, "version_id", None)
        if ingestion is not None:
            if not await self._revalidate_ingestion(ingestion):
                await self.ingestion_store.fail_or_quarantine(  # type: ignore[union-attr]
                    ctx.tenant_id,
                    UUID(ingestion["id"]),
                    IngestionStatus.FAILED,
                    "commit_authorization_revoked",
                )
                raise ApiError(
                    "permission_denied", "Authorization is no longer valid", status_code=403
                )
            await self.ingestion_store.record_provider_result(  # type: ignore[union-attr]
                ctx.tenant_id,
                UUID(ingestion["id"]),
                provider_etag=provider_etag,
                provider_version_id=provider_version,
                actual_size=obj.content_length,
                actual_content_type=obj.content_type,
                checksum=requested_checksum,
            )
            try:
                committed = await self.ingestion_store.commit_verified_file(  # type: ignore[union-attr]
                    ctx.tenant_id, UUID(ingestion["id"])
                )
                file_object = committed.get("file_object")
                if file_object is not None:
                    committed = dict(committed)
                    committed["file_object"] = self._public_file(
                        await self._resolve_space(ctx.tenant_id, command.storage_space_id),
                        file_object,
                    )
                return self._public_ingestion_result(committed)
            except Exception as exc:
                await self.ingestion_store.fail_or_quarantine(  # type: ignore[union-attr]
                    ctx.tenant_id,
                    UUID(ingestion["id"]),
                    IngestionStatus.RECONCILIATION_REQUIRED,
                    "database_commit_failed",
                )
                raise ApiError(
                    "storage_unavailable", "Upload requires reconciliation", status_code=503
                ) from exc
        file_data = {
            "tenant_id": str(ctx.tenant_id),
            "storage_space_id": record["storage_space_id"],
            "object_key": record["object_key"],
            "content_length": record["content_length"],
            "content_type": record["content_type"],
            "checksum": record.get("checksum"),
            "etag": provider_etag,
            "version_id": provider_version,
            "idempotency_key": idempotency_key,
        }
        completed = await self.store.complete_upload(ctx.tenant_id, UUID(upload_id), file_data)
        space = await self._resolve_space(ctx.tenant_id, command.storage_space_id)
        file_object = completed.get("file_object")
        # Keep the no-ingestion fallback contract-equivalent to the ingestion
        # path: clients always receive a completion result, never an upload
        # session DTO whose shape happens to depend on deployment wiring.
        return {
            "id": str(completed["id"]),
            "status": str(completed.get("status", "completed")),
            "storage_space_id": str(completed.get("storage_space_id")),
            "etag": completed.get("etag")
            or (file_object.get("etag") if isinstance(file_object, dict) else None),
            "file_object": self._public_file(space, file_object)
            if isinstance(file_object, dict)
            else None,
        }

    async def create_presigned_download(
        self, ctx: PrincipalContext, space_id: str, body: Any
    ) -> dict[str, Any]:
        if self.object_storage is None:
            raise ApiError("internal_error", "Object storage is not configured", status_code=500)
        # Look up file by file_id (tenant-scoped) instead of accepting raw object_key
        file_record = await self.store.get_file(ctx.tenant_id, UUID(space_id), UUID(body.file_id))
        if file_record is None:
            raise ApiError("resource_not_found", "File not found", status_code=404)
        command = await self._command_for_record(ctx, file_record, "presigned_urls.issue")
        url = await self.object_storage.presign_get(command.provider_target, body.ttl_seconds)
        return {
            "method": "GET",
            "url": url,
            "file_id": body.file_id,
            "expires_in": body.ttl_seconds,
        }

    # ── Multipart ──────────────────────────────────────────────────────────

    async def create_multipart_upload(
        self,
        ctx: PrincipalContext,
        space_id: str,
        body: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if self.object_storage is None:
            raise ApiError(
                "storage_capability_unsupported",
                "Multipart storage is not configured",
                status_code=422,
            )
        command = await self._command(
            ctx,
            space_id,
            body.object_key,
            "files.write",
            idempotency_key=idempotency_key,
            semantics={
                "content_length": body.content_length,
                "content_type": body.content_type.lower(),
            },
        )
        data = {
            "principal_id": str(ctx.principal_id),
            "membership_id": str(ctx.membership_id) if ctx.membership_id else None,
            "object_key": command.physical_key,
            "provider_target_version": command.provider_target_version,
            "content_length": body.content_length,
            "content_type": body.content_type,
            "idempotency_key": idempotency_key,
        }
        space = await self._resolve_space(ctx.tenant_id, command.storage_space_id)
        data.update(
            {
                "application_id": space.get("application_id"),
                "storage_namespace": space.get("storage_namespace"),
                "profile_version": space.get("profile_version", 1),
            }
        )
        if self.ingestion_store is None:
            record = await self.store.create_multipart(
                ctx.tenant_id, command.storage_space_id, data
            )
            ingestion = None
        else:
            record = await self.ingestion_store.create_multipart_intent(
                ctx.tenant_id,
                {
                    **data,
                    "storage_space_id": str(command.storage_space_id),
                    "expires_at": datetime.now(UTC) + timedelta(hours=24),
                },
                self._ingestion_data(command, idempotency_key),
            )
            ingestion = {"id": record["ingestion_id"]}
            if record.pop("replayed", False):
                return self._public_multipart(
                    await self._resolve_space(ctx.tenant_id, command.storage_space_id), record
                )
        provider_upload_id: str | None = None
        try:
            provider_upload_id = await self.object_storage.create_multipart_upload(
                command.provider_target, body.content_type
            )
            try:
                created = await self.store.set_multipart_provider_id(
                    ctx.tenant_id, UUID(record["id"]), provider_upload_id
                )
            except Exception:
                # Make a second persistence attempt so a cleanup failure does
                # not lose the provider upload id needed by reconciliation.
                try:
                    await self.store.set_multipart_provider_id(
                        ctx.tenant_id, UUID(record["id"]), provider_upload_id
                    )
                except Exception as retry_exc:
                    raise RuntimeError(
                        "multipart provider id could not be persisted"
                    ) from retry_exc
                raise
            return self._public_multipart(
                await self._resolve_space(ctx.tenant_id, command.storage_space_id), created
            )
        except Exception as exc:
            if provider_upload_id is not None:
                try:
                    await self.object_storage.abort_multipart_upload(
                        command.provider_target, provider_upload_id
                    )
                except Exception as abort_exc:
                    if ingestion is not None:
                        await self.ingestion_store.fail_or_quarantine(  # type: ignore[union-attr]
                            ctx.tenant_id,
                            UUID(ingestion["id"]),
                            IngestionStatus.RECONCILIATION_REQUIRED,
                            "multipart_provider_abort_failed",
                        )
                    raise ApiError(
                        "storage_unavailable",
                        "Multipart provider cleanup requires reconciliation",
                        status_code=503,
                    ) from abort_exc
            await self.store.abort_multipart(ctx.tenant_id, UUID(record["id"]))
            if ingestion is not None:
                await self.ingestion_store.fail_or_quarantine(  # type: ignore[union-attr]
                    ctx.tenant_id,
                    UUID(ingestion["id"]),
                    IngestionStatus.RECONCILIATION_REQUIRED,
                    "multipart_provider_create_failed",
                )
            raise ApiError(
                "storage_unavailable", "Multipart creation requires reconciliation", status_code=503
            ) from exc

    async def get_multipart_upload(
        self, ctx: PrincipalContext, multipart_id: str
    ) -> dict[str, Any]:
        result = await self.store.get_multipart(ctx.tenant_id, UUID(multipart_id))
        if result is None:
            raise ApiError("resource_not_found", "Multipart upload not found", status_code=404)
        FileAuthGuard.check_ownership(result, ctx)
        await self._command_for_record(ctx, result, "files.write")
        await self._ensure_multipart_active(result)
        return self._public_multipart(
            await self._resolve_space(ctx.tenant_id, UUID(result["storage_space_id"])), result
        )

    async def abort_multipart_upload(
        self,
        ctx: PrincipalContext,
        multipart_id: str,
        idempotency_key: str | None = None,
    ) -> None:
        record = await self.store.get_multipart(ctx.tenant_id, UUID(multipart_id))
        if record is None:
            raise ApiError("resource_not_found", "Multipart upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        await self._command_for_record(ctx, record, "files.write", idempotency_key=idempotency_key)
        await self._ensure_multipart_active(record)
        provider_upload_id = record.get("provider_upload_id")
        if self.object_storage is not None and provider_upload_id:
            try:
                command = await self._command_for_record(ctx, record, "files.write")
                await self.object_storage.abort_multipart_upload(
                    command.provider_target, provider_upload_id
                )
            except Exception as exc:
                raise ApiError(
                    "storage_unavailable", "Multipart abort requires retry", status_code=503
                ) from exc
        await self.store.abort_multipart(
            ctx.tenant_id, UUID(multipart_id), idempotency_key=idempotency_key
        )

    async def list_multipart_parts(
        self, ctx: PrincipalContext, multipart_id: str
    ) -> list[dict[str, Any]]:
        record = await self.store.get_multipart(ctx.tenant_id, UUID(multipart_id))
        if record is None:
            raise ApiError("resource_not_found", "Multipart upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        await self._command_for_record(ctx, record, "files.write")
        await self._ensure_multipart_active(record)
        return await self.store.list_multipart_parts(ctx.tenant_id, UUID(multipart_id))

    async def upload_multipart_part(
        self,
        ctx: PrincipalContext,
        multipart_id: str,
        part_number: int,
        body: bytes,
        content_length: int,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        record = await self.store.get_multipart(ctx.tenant_id, UUID(multipart_id))
        if record is None:
            raise ApiError("resource_not_found", "Multipart upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        await self._command_for_record(
            ctx,
            record,
            "files.write",
            idempotency_key=idempotency_key,
            semantics={
                "part_number": part_number,
                "content_length": content_length,
            },
        )
        await self._ensure_multipart_active(record)
        if content_length != len(body) or content_length <= 0:
            raise ApiError("multipart_parts_invalid", "Part length mismatch", status_code=409)
        if part_number < 1 or part_number > 10000:
            raise ApiError("multipart_parts_invalid", "Part number is invalid", status_code=422)
        if idempotency_key:
            existing_parts = await self.store.list_multipart_parts(
                ctx.tenant_id, UUID(multipart_id)
            )
            content_sha256 = hashlib.sha256(body).hexdigest()
            existing = next(
                (item for item in existing_parts if int(item["part_number"]) == part_number),
                None,
            )
            if (
                existing is not None
                and existing.get("idempotency_key") == idempotency_key
                and (
                    int(existing.get("content_length", -1)) != content_length
                    or existing.get("content_sha256") != content_sha256
                )
            ):
                raise ApiError(
                    "idempotency_key_reused",
                    "Idempotency-Key was reused with different part content",
                    status_code=409,
                )
            replay = next(
                (
                    item
                    for item in existing_parts
                    if int(item["part_number"]) == part_number
                    and item.get("idempotency_key") == idempotency_key
                    and int(item.get("content_length", -1)) == content_length
                    and item.get("content_sha256") == content_sha256
                ),
                None,
            )
            if replay is not None:
                return replay
        provider_upload_id = record.get("provider_upload_id")
        if not provider_upload_id or self.object_storage is None:
            raise ApiError(
                "storage_capability_unsupported",
                "Multipart provider session is unavailable",
                status_code=422,
            )
        command = await self._command_for_record(ctx, record, "files.write")
        result = await self.object_storage.upload_part(
            command.provider_target, str(provider_upload_id), part_number, body
        )
        etag = str(result.get("etag") or "")
        if not etag:
            raise ApiError(
                "storage_unavailable", "Multipart provider returned no ETag", status_code=503
            )
        return await self.store.record_multipart_part(
            ctx.tenant_id,
            UUID(multipart_id),
            part_number,
            {
                "etag": etag,
                "content_length": content_length,
                "idempotency_key": idempotency_key,
                "content_sha256": hashlib.sha256(body).hexdigest(),
            },
        )

    async def complete_multipart_upload(
        self,
        ctx: PrincipalContext,
        multipart_id: str,
        body: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        record = await self.store.get_multipart(ctx.tenant_id, UUID(multipart_id))
        if record is None:
            raise ApiError("resource_not_found", "Multipart upload not found", status_code=404)
        FileAuthGuard.check_ownership(record, ctx)
        command = await self._command_for_record(
            ctx,
            record,
            "files.write",
            idempotency_key=idempotency_key,
            semantics={
                "parts": [{"part_number": p.part_number, "etag": p.etag} for p in body.parts]
            },
        )
        await self._ensure_multipart_active(record)
        provider_upload_id = record.get("provider_upload_id")
        if not provider_upload_id or self.object_storage is None:
            raise ApiError(
                "storage_capability_unsupported",
                "Multipart provider session is unavailable",
                status_code=422,
            )
        stored_parts = await self.store.list_multipart_parts(ctx.tenant_id, UUID(multipart_id))
        stored_by_number = {int(p["part_number"]): p for p in stored_parts}
        requested_numbers = [int(p.part_number) for p in body.parts]
        if requested_numbers != sorted(set(requested_numbers)):
            raise ApiError(
                "multipart_parts_invalid",
                "Multipart parts must be unique and ordered",
                status_code=409,
            )
        provider_parts: list[dict[str, object]] = []
        total_size = 0
        for part in body.parts:
            stored = stored_by_number.get(part.part_number)
            if stored is None or stored.get("etag") != part.etag:
                raise ApiError(
                    "multipart_parts_invalid",
                    "Multipart part does not match stored metadata",
                    status_code=409,
                )
            provider_parts.append({"part_number": part.part_number, "etag": part.etag})
            total_size += int(stored.get("content_length", 0))
        if total_size != int(record["content_length"]):
            raise ApiError(
                "multipart_parts_invalid",
                "Multipart size does not match declaration",
                status_code=409,
            )
        provider_inventory = await self.object_storage.list_parts(
            command.provider_target, provider_upload_id
        )
        provider_by_number = {
            int(cast(int | str, part["part_number"])): part for part in provider_inventory
        }
        for part in provider_parts:
            provider = provider_by_number.get(int(cast(int | str, part["part_number"])))
            if provider is None or provider.get("etag") != part["etag"]:
                raise ApiError(
                    "multipart_parts_invalid",
                    "Multipart provider part metadata mismatch",
                    status_code=409,
                )
        ingestion = await self._ingestion_for_session(ctx.tenant_id, multipart_id=multipart_id)
        try:
            metadata = await self.object_storage.complete_multipart_upload(
                command.provider_target, provider_upload_id, provider_parts
            )
            if (
                getattr(metadata, "key", command.physical_key) != command.physical_key
                or getattr(metadata, "content_length", None) != total_size
            ):
                raise ApiError(
                    "upload_verification_failed",
                    "Completed multipart object metadata mismatch",
                    status_code=409,
                )
        except ApiError:
            if ingestion is not None:
                await self.ingestion_store.fail_or_quarantine(  # type: ignore[union-attr]
                    ctx.tenant_id,
                    UUID(ingestion["id"]),
                    IngestionStatus.FAILED,
                    "multipart_verification_failed",
                )
            raise
        except Exception as exc:
            if ingestion is not None:
                await self.ingestion_store.fail_or_quarantine(  # type: ignore[union-attr]
                    ctx.tenant_id,
                    UUID(ingestion["id"]),
                    IngestionStatus.RECONCILIATION_REQUIRED,
                    "multipart_provider_failed",
                )
            raise ApiError(
                "storage_unavailable",
                "Multipart completion requires reconciliation",
                status_code=503,
            ) from exc
        data = {
            "parts": provider_parts,
            "content_length": total_size,
            "content_type": getattr(metadata, "content_type", record["content_type"]),
            "etag": getattr(metadata, "etag", None),
            "idempotency_key": idempotency_key,
        }
        if ingestion is not None:
            if not await self._revalidate_ingestion(ingestion):
                await self.ingestion_store.fail_or_quarantine(  # type: ignore[union-attr]
                    ctx.tenant_id,
                    UUID(ingestion["id"]),
                    IngestionStatus.FAILED,
                    "commit_authorization_revoked",
                )
                raise ApiError(
                    "permission_denied", "Authorization is no longer valid", status_code=403
                )
            await self.ingestion_store.record_provider_result(  # type: ignore[union-attr]
                ctx.tenant_id,
                UUID(ingestion["id"]),
                provider_etag=getattr(metadata, "etag", None),
                provider_version_id=getattr(metadata, "version_id", None),
                actual_size=metadata.content_length,
                actual_content_type=metadata.content_type,
                checksum=None,
            )
            try:
                committed = await self.ingestion_store.commit_verified_file(  # type: ignore[union-attr]
                    ctx.tenant_id, UUID(ingestion["id"])
                )
                file_object = committed.get("file_object")
                if file_object is not None:
                    committed = dict(committed)
                    committed["file_object"] = self._public_file(
                        await self._resolve_space(ctx.tenant_id, command.storage_space_id),
                        file_object,
                    )
                return self._public_ingestion_result(committed)
            except Exception as exc:
                await self.ingestion_store.fail_or_quarantine(  # type: ignore[union-attr]
                    ctx.tenant_id,
                    UUID(ingestion["id"]),
                    IngestionStatus.RECONCILIATION_REQUIRED,
                    "multipart_database_commit_failed",
                )
                raise ApiError(
                    "storage_unavailable",
                    "Multipart completion requires reconciliation",
                    status_code=503,
                ) from exc
        completed = await self.store.complete_multipart(ctx.tenant_id, UUID(multipart_id), data)
        space = await self._resolve_space(ctx.tenant_id, command.storage_space_id)
        result = self._public_multipart(space, completed)
        file_object = completed.get("file_object")
        result["file_object"] = (
            self._public_file(space, file_object) if isinstance(file_object, dict) else None
        )
        result["etag"] = data.get("etag")
        return result
