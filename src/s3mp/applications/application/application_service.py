"""Tenant-scoped application and API key application services."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from s3mp.applications.domain.credentials import (
    ApiKeyCredentialService,
    key_is_usable,
    orphaned_application,
    parse_credential,
)
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext


def _public_api_key(record: dict[str, Any]) -> dict[str, Any]:
    """Remove verification material before returning an API-key record publicly."""
    return {key: value for key, value in record.items() if key != "secret_digest"}


class ApplicationStore(Protocol):
    async def list_apps(
        self, tenant_id: UUID, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    async def get_app(self, tenant_id: UUID, app_id: UUID) -> dict[str, Any] | None: ...

    async def create_app(self, tenant_id: UUID, name: str, principal_id: UUID) -> dict[str, Any]: ...

    async def update_app(
        self, tenant_id: UUID, app_id: UUID, name: str | None
    ) -> dict[str, Any] | None: ...

    async def takeover_app(
        self, tenant_id: UUID, app_id: UUID, owner_principal_id: UUID, reason: str
    ) -> dict[str, Any] | None: ...

    async def list_owners(self, tenant_id: UUID, app_id: UUID) -> list[UUID]: ...
    async def list_active_owners(self, tenant_id: UUID, app_id: UUID) -> list[UUID]: ...
    async def recompute_owner_state_for_principal(self, tenant_id: UUID, owner_principal_id: UUID) -> int: ...
    async def scan_ownerless_applications(self, tenant_id: UUID) -> int: ...


class PermissionAuthorizer(Protocol):
    async def require_permission(self, context: PrincipalContext, permission: str) -> None: ...


class ApiKeyStore(Protocol):
    async def list_active_owners(self, tenant_id: UUID, app_id: UUID) -> list[UUID]: ...

    async def list_keys(
        self, tenant_id: UUID, app_id: UUID, limit: int, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    async def get_key(self, tenant_id: UUID, key_id: UUID) -> dict[str, Any] | None: ...

    async def create_key(
        self,
        tenant_id: UUID,
        app_id: UUID,
        key_id: str,
        digest: bytes,
        pepper_version: int,
        scopes: list[str],
        expires_at: datetime,
        **audit: Any,
    ) -> dict[str, Any]: ...

    async def update_key(
        self,
        tenant_id: UUID,
        key_id: UUID,
        status: str,
        revoked_at: datetime | None,
        last_used_at: datetime | None,
        **audit: Any,
    ) -> dict[str, Any] | None: ...

    async def find_by_key_id(self, key_id: str) -> dict[str, Any] | None: ...


@dataclass
class ApplicationService:
    store: ApplicationStore
    authorizer: PermissionAuthorizer | None = None

    async def list_apps(
        self, context: PrincipalContext, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        await self._require(context, "applications.read")
        return await self.store.list_apps(context.tenant_id, min(limit, 200), cursor)

    async def get_app(self, context: PrincipalContext, app_id: UUID) -> dict[str, Any]:
        result = await self.store.get_app(context.tenant_id, app_id)
        if result is None:
            raise ApiError("resource_not_found", "Application not found", status_code=404)
        await self._require_owner_or_permission(context, app_id, "applications.read")
        return result

    async def create_app(self, context: PrincipalContext, name: str) -> dict[str, Any]:
        await self._require(context, "applications.manage")
        return await self.store.create_app(context.tenant_id, name, context.principal_id)

    async def update_app(
        self, context: PrincipalContext, app_id: UUID, name: str | None
    ) -> dict[str, Any]:
        await self._require_owner_or_permission(context, app_id, "applications.manage")
        result = await self.store.update_app(context.tenant_id, app_id, name)
        if result is None:
            raise ApiError("resource_not_found", "Application not found", status_code=404)
        return result

    async def takeover_app(
        self, context: PrincipalContext, app_id: UUID, reason: str
    ) -> dict[str, Any]:
        """Reactivate an ownerless application under a newly accountable member.

        This deliberately preserves valid API keys: the application's bumped
        authorization version already blocked them while pending, and no key
        material is read or returned during recovery.
        """
        if context.subject_kind == "application":
            raise ApiError("permission_denied", "API keys cannot take over applications", status_code=403)
        await self._require(context, "applications.manage")
        current = await self.store.get_app(context.tenant_id, app_id)
        if current is None:
            raise ApiError("resource_not_found", "Application not found", status_code=404)
        if current["status"] != "pending_takeover":
            raise ApiError("conflict", "Application does not require takeover", status_code=409)
        result = await self.store.takeover_app(
            context.tenant_id, app_id, context.principal_id, reason
        )
        if result is None:
            raise ApiError("resource_not_found", "Application not found", status_code=404)
        return result

    async def check_orphan(self, tenant_id: UUID, app_id: UUID) -> bool:
        owners = await self.store.list_owners(tenant_id, app_id)
        active_owners = await self.store.list_active_owners(tenant_id, app_id)
        return orphaned_application(set(owners), set(active_owners))

    async def scan_ownerless(self, context: PrincipalContext) -> int:
        await self._require(context, "applications.manage")
        return await self.store.scan_ownerless_applications(context.tenant_id)

    async def _require(self, context: PrincipalContext, permission: str) -> None:
        if self.authorizer is None:
            raise ApiError("internal_error", "Authorization service is not configured", status_code=500)
        await self.authorizer.require_permission(context, permission)

    async def _require_owner_or_permission(
        self, context: PrincipalContext, app_id: UUID, permission: str
    ) -> None:
        owners = await self.store.list_active_owners(context.tenant_id, app_id)
        if context.principal_id in owners:
            return
        await self._require(context, permission)


@dataclass
class ApiKeyService:
    store: ApiKeyStore
    credential_service: ApiKeyCredentialService
    authorizer: PermissionAuthorizer | None = None

    async def list_keys(
        self, context: PrincipalContext, app_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        await self._require_owner_or_permission(context, app_id, "api_keys.read")
        items, next_cursor = await self.store.list_keys(context.tenant_id, app_id, min(limit, 200), cursor)
        return [_public_api_key(item) for item in items], next_cursor

    async def get_key(self, context: PrincipalContext, key_id: UUID) -> dict[str, Any]:
        result = await self.store.get_key(context.tenant_id, key_id)
        if result is None:
            raise ApiError("resource_not_found", "API key not found", status_code=404)
        await self._require_owner_or_permission(
            context, UUID(str(result["application_id"])), "api_keys.read"
        )
        return _public_api_key(result)

    async def issue(
        self, context: PrincipalContext, app_id: UUID, scopes: list[str], ttl_days: int = 90
    ) -> dict[str, Any]:
        await self._require_owner_or_permission(context, app_id, "api_keys.manage")
        issued = self.credential_service.issue()
        digest = self.credential_service.digest(issued.secret)
        expires_at = datetime.now(UTC) + timedelta(days=ttl_days)
        record = await self.store.create_key(
            context.tenant_id, app_id, issued.key_id, digest,
            self.credential_service.pepper_version, scopes, expires_at,
            actor_principal_id=context.principal_id,
            audit_action="api_key.issued",
        )
        record["secret"] = issued.secret
        record["credential"] = issued.credential
        return _public_api_key(record)

    async def rotate(
        self, context: PrincipalContext, key_id: UUID, overlap_seconds: int = 300
    ) -> dict[str, Any]:
        existing = await self.get_key(context, key_id)
        await self._require_owner_or_permission(
            context, UUID(str(existing["application_id"])), "api_keys.manage"
        )
        issued = self.credential_service.issue()
        digest = self.credential_service.digest(issued.secret)
        expires_at = datetime.now(UTC) + timedelta(days=90)
        await self.store.update_key(
            context.tenant_id, key_id, "revoked",
            datetime.now(UTC) + timedelta(seconds=overlap_seconds), None,
            actor_principal_id=context.principal_id,
            audit_action="api_key.rotated",
            reason_code="rotation",
        )
        record = await self.store.create_key(
            context.tenant_id, existing["application_id"], issued.key_id, digest,
            self.credential_service.pepper_version,
            existing.get("scopes", []),
            expires_at,
            actor_principal_id=context.principal_id,
            audit_action="api_key.rotation_replacement_issued",
        )
        record["secret"] = issued.secret
        record["credential"] = issued.credential
        return _public_api_key(record)

    async def revoke(
        self, context: PrincipalContext, key_id: UUID, reason: str
    ) -> dict[str, Any]:
        existing = await self.get_key(context, key_id)
        await self._require_owner_or_permission(
            context, UUID(str(existing["application_id"])), "api_keys.manage"
        )
        result = await self.store.update_key(
            context.tenant_id, key_id, "revoked", datetime.now(UTC), None,
            actor_principal_id=context.principal_id,
            audit_action="api_key.revoked",
            reason_code="operator_requested",
        )
        if result is None:
            raise ApiError("resource_not_found", "API key not found", status_code=404)
        return _public_api_key(result)

    async def authenticate(
        self, credential: str
    ) -> tuple[UUID, UUID, dict[str, Any]]:
        key_id_str, secret = parse_credential(credential)
        record = await self.store.find_by_key_id(key_id_str)
        if record is None:
            raise ApiError("authentication_required", "Invalid API key", status_code=401)
        if not self.credential_service.verify(secret, record["secret_digest"]):
            raise ApiError("authentication_required", "Invalid API key", status_code=401)
        if not key_is_usable(
            status=str(record["status"]),
            expires_at=record["expires_at"],
        ):
            raise ApiError(
                "authentication_required", "API key is revoked or expired", status_code=401
            )
        if (
            record.get("application_status") != "active"
            or not record.get("principal_enabled", False)
            or record.get("principal_type") != "application"
        ):
            raise ApiError("authentication_required", "Application is not active", status_code=401)
        return record["tenant_id"], UUID(str(record["id"])), record

    async def _require_owner_or_permission(
        self, context: PrincipalContext, app_id: UUID, permission: str
    ) -> None:
        owners = await self.store.list_active_owners(context.tenant_id, app_id)
        if context.principal_id in owners:
            return
        if self.authorizer is None:
            raise ApiError("internal_error", "Authorization service is not configured", status_code=500)
        try:
            await self.authorizer.require_permission(context, permission)
        except ApiError:
            await self._audit_denial(context, app_id, permission, "owner_or_permission_denied")
            raise

    async def audit_management_denial(self, context: PrincipalContext) -> None:
        await self._audit_denial(context, context.application_id, "management.route", "api_key_forbidden")

    async def _audit_denial(
        self, context: PrincipalContext, app_id: UUID | None, permission: str, reason_code: str
    ) -> None:
        writer = getattr(self.store, "record_security_audit", None)
        if writer is not None:
            await writer(
                context.tenant_id,
                context.principal_id,
                "authorization.denied",
                "application",
                str(app_id) if app_id else None,
                {"permission": permission, "reason_code": reason_code},
            )
