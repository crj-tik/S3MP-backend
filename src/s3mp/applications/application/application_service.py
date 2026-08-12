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

    async def list_owners(self, tenant_id: UUID, app_id: UUID) -> list[UUID]: ...


class ApiKeyStore(Protocol):
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
    ) -> dict[str, Any]: ...

    async def update_key(
        self,
        tenant_id: UUID,
        key_id: UUID,
        status: str,
        revoked_at: datetime | None,
        last_used_at: datetime | None,
    ) -> dict[str, Any] | None: ...

    async def find_by_key_id(self, key_id: str) -> dict[str, Any] | None: ...


@dataclass
class ApplicationService:
    store: ApplicationStore

    async def list_apps(
        self, tenant_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        return await self.store.list_apps(tenant_id, min(limit, 200), cursor)

    async def get_app(self, tenant_id: UUID, app_id: UUID) -> dict[str, Any]:
        result = await self.store.get_app(tenant_id, app_id)
        if result is None:
            raise ApiError("resource_not_found", "Application not found", status_code=404)
        return result

    async def create_app(self, tenant_id: UUID, name: str, principal_id: UUID) -> dict[str, Any]:
        return await self.store.create_app(tenant_id, name, principal_id)

    async def update_app(
        self, tenant_id: UUID, app_id: UUID, name: str | None
    ) -> dict[str, Any]:
        result = await self.store.update_app(tenant_id, app_id, name)
        if result is None:
            raise ApiError("resource_not_found", "Application not found", status_code=404)
        return result

    async def check_orphan(self, tenant_id: UUID, app_id: UUID) -> bool:
        owners = await self.store.list_owners(tenant_id, app_id)
        return orphaned_application(set(owners), set(owners))


@dataclass
class ApiKeyService:
    store: ApiKeyStore
    credential_service: ApiKeyCredentialService

    async def list_keys(
        self, tenant_id: UUID, app_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        items, next_cursor = await self.store.list_keys(tenant_id, app_id, min(limit, 200), cursor)
        return [_public_api_key(item) for item in items], next_cursor

    async def get_key(self, tenant_id: UUID, key_id: UUID) -> dict[str, Any]:
        result = await self.store.get_key(tenant_id, key_id)
        if result is None:
            raise ApiError("resource_not_found", "API key not found", status_code=404)
        return _public_api_key(result)

    async def issue(
        self, tenant_id: UUID, app_id: UUID, scopes: list[str], ttl_days: int = 90
    ) -> dict[str, Any]:
        issued = self.credential_service.issue()
        digest = self.credential_service.digest(issued.secret)
        expires_at = datetime.now(UTC) + timedelta(days=ttl_days)
        record = await self.store.create_key(
            tenant_id, app_id, issued.key_id, digest,
            self.credential_service.pepper_version, scopes, expires_at,
        )
        record["secret"] = issued.secret
        record["credential"] = issued.credential
        return _public_api_key(record)

    async def rotate(
        self, tenant_id: UUID, key_id: UUID, overlap_seconds: int = 300
    ) -> dict[str, Any]:
        existing = await self.get_key(tenant_id, key_id)
        issued = self.credential_service.issue()
        digest = self.credential_service.digest(issued.secret)
        expires_at = datetime.now(UTC) + timedelta(days=90)
        await self.store.update_key(
            tenant_id, key_id, "revoked",
            datetime.now(UTC) + timedelta(seconds=overlap_seconds), None,
        )
        record = await self.store.create_key(
            tenant_id, existing["application_id"], issued.key_id, digest,
            self.credential_service.pepper_version,
            existing.get("scopes", []),
            expires_at,
        )
        record["secret"] = issued.secret
        record["credential"] = issued.credential
        return _public_api_key(record)

    async def revoke(
        self, tenant_id: UUID, key_id: UUID, reason: str
    ) -> dict[str, Any]:
        result = await self.store.update_key(
            tenant_id, key_id, "revoked", datetime.now(UTC), None
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
        return record["tenant_id"], UUID(key_id_str), record
