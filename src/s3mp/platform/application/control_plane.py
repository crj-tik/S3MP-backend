"""Read-only platform control-plane queries and safe summaries."""

from typing import Protocol, cast
from uuid import UUID

from s3mp.common.errors import ApiError
from s3mp.common.logging import instrument_service_mutations
from s3mp.identity.application.security import PasswordHasher
from s3mp.platform.application.account_import import (
    ImportCandidate,
    decode_xlsx,
    parse_account_import,
)
from s3mp.platform.domain.context import PlatformContext
from s3mp.platform.domain.support_access import SupportAccessStatus


class PlatformControlPlaneStore(Protocol):
    async def list_platform_accounts(
        self,
        *,
        limit: int,
        cursor: UUID | None,
        query: str | None,
        status: str | None,
        include_deleted: bool = False,
    ) -> tuple[list[dict[str, object]], UUID | None]: ...

    async def get_platform_account(self, user_id: UUID) -> dict[str, object] | None: ...

    async def delete_platform_account(
        self, *, user_id: UUID, actor_user_id: UUID, reason: str
    ) -> dict[str, object] | None: ...

    async def restore_platform_account(
        self, *, user_id: UUID, actor_user_id: UUID, reason: str
    ) -> dict[str, object] | None: ...

    async def reset_platform_account_password(
        self, *, user_id: UUID, actor_user_id: UUID, password_hash: str
    ) -> dict[str, object] | None: ...

    async def import_platform_accounts(
        self, *, actor_user_id: UUID, candidates: list[dict[str, object]]
    ) -> list[dict[str, object]]: ...

    async def list_platform_roles(
        self, *, limit: int, cursor: UUID | None
    ) -> tuple[list[dict[str, object]], UUID | None]: ...

    async def list_platform_role_bindings(
        self, *, limit: int, cursor: UUID | None
    ) -> tuple[list[dict[str, object]], UUID | None]: ...

    async def list_support_access(
        self, *, limit: int, cursor: UUID | None, status: SupportAccessStatus | None
    ) -> tuple[list[dict[str, object]], UUID | None]: ...

    async def get_support_access(self, request_id: UUID) -> dict[str, object] | None: ...

    async def list_platform_audit_events(
        self,
        *,
        limit: int,
        cursor: UUID | None,
        action: str | None,
        resource_type: str | None,
        resource_id: str | None,
    ) -> tuple[list[dict[str, object]], UUID | None]: ...

    async def get_platform_audit_event(self, event_id: UUID) -> dict[str, object] | None: ...


@instrument_service_mutations("platform.control")
class PlatformControlPlaneService:
    def __init__(self, store: PlatformControlPlaneStore) -> None:
        self._store = store
        self._password_hasher = PasswordHasher()

    async def list_accounts(
        self,
        _actor: PlatformContext,
        *,
        limit: int,
        cursor: UUID | None,
        query: str | None,
        status: str | None,
        include_deleted: bool = False,
    ) -> tuple[list[dict[str, object]], UUID | None]:
        if include_deleted and "platform.audit.read" not in _actor.permissions:
            raise ApiError("permission_denied", "Historical account access is not permitted", 403)
        return await self._store.list_platform_accounts(
            limit=limit,
            cursor=cursor,
            query=query,
            status=status,
            include_deleted=include_deleted,
        )

    async def get_account(self, _actor: PlatformContext, user_id: UUID) -> dict[str, object] | None:
        return await self._store.get_platform_account(user_id)

    async def delete_account(
        self, actor: PlatformContext, user_id: UUID, reason: str
    ) -> dict[str, object]:
        result = await self._store.delete_platform_account(
            user_id=user_id, actor_user_id=actor.user_id, reason=reason
        )
        if result is None:
            raise ApiError("resource_not_found", "Platform account not found", status_code=404)
        return result

    async def restore_account(
        self, actor: PlatformContext, user_id: UUID, reason: str
    ) -> dict[str, object]:
        try:
            result = await self._store.restore_platform_account(
                user_id=user_id, actor_user_id=actor.user_id, reason=reason
            )
        except ValueError as exc:
            raise ApiError("conflict", str(exc), status_code=409) from exc
        if result is None:
            raise ApiError(
                "resource_not_found", "Deleted platform account not found", status_code=404
            )
        return result

    async def reset_account_password(
        self, actor: PlatformContext, user_id: UUID, password: str
    ) -> dict[str, object]:
        if len(password) < 8:
            raise ApiError("validation_failed", "Password must be at least 8 characters", 422)
        result = await self._store.reset_platform_account_password(
            user_id=user_id,
            actor_user_id=actor.user_id,
            password_hash=self._password_hasher.hash(password),
        )
        if result is None:
            raise ApiError("resource_not_found", "Active platform account not found", 404)
        return result

    async def import_accounts(
        self, actor: PlatformContext, *, filename: str, content_base64: str
    ) -> dict[str, object]:
        candidates, errors = parse_account_import(decode_xlsx(filename, content_base64))
        stored = await self._store.import_platform_accounts(
            actor_user_id=actor.user_id,
            candidates=[self._hashed_candidate(candidate) for candidate in candidates],
        )
        rows: list[dict[str, object]] = [
            {
                "row": error.row,
                "email": error.email,
                "employee_number": error.employee_number,
                "status": "rejected",
                "code": error.code,
                "message": error.message,
            }
            for error in errors
        ]
        rows.extend(stored)
        rows.sort(key=lambda item: cast(int, item["row"]))
        created_count = sum(item["status"] == "created" for item in rows)
        return {
            "total_rows": len(rows),
            "created_count": created_count,
            "rejected_count": len(rows) - created_count,
            "rows": rows,
        }

    def _hashed_candidate(self, candidate: ImportCandidate) -> dict[str, object]:
        return {
            "row": candidate.row,
            "email": candidate.email,
            "normalized_email": candidate.normalized_email,
            "employee_number": candidate.employee_number,
            "normalized_employee_number": candidate.normalized_employee_number,
            "display_name": candidate.display_name,
            "password_hash": self._password_hasher.hash(candidate.password),
        }

    async def list_roles(
        self, _actor: PlatformContext, *, limit: int, cursor: UUID | None
    ) -> tuple[list[dict[str, object]], UUID | None]:
        return await self._store.list_platform_roles(limit=limit, cursor=cursor)

    async def list_role_bindings(
        self, _actor: PlatformContext, *, limit: int, cursor: UUID | None
    ) -> tuple[list[dict[str, object]], UUID | None]:
        return await self._store.list_platform_role_bindings(limit=limit, cursor=cursor)

    async def list_support(
        self,
        _actor: PlatformContext,
        *,
        limit: int,
        cursor: UUID | None,
        status: SupportAccessStatus | None,
    ) -> tuple[list[dict[str, object]], UUID | None]:
        return await self._store.list_support_access(limit=limit, cursor=cursor, status=status)

    async def get_support(
        self, _actor: PlatformContext, request_id: UUID
    ) -> dict[str, object] | None:
        return await self._store.get_support_access(request_id)

    async def list_audit(
        self,
        _actor: PlatformContext,
        *,
        limit: int,
        cursor: UUID | None,
        action: str | None,
        resource_type: str | None,
        resource_id: str | None,
    ) -> tuple[list[dict[str, object]], UUID | None]:
        return await self._store.list_platform_audit_events(
            limit=limit,
            cursor=cursor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
        )

    async def get_audit(self, _actor: PlatformContext, event_id: UUID) -> dict[str, object] | None:
        return await self._store.get_platform_audit_event(event_id)
