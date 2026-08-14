"""Global browser account authentication, deliberately separate from tenant sessions."""

import re
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from s3mp.common.errors import ApiError
from s3mp.identity.application.security import (
    AuthenticationFailed,
    LocalPasswordAuthenticator,
    LoginRateLimited,
    PasswordCredential,
    PasswordHasher,
    SessionTokenService,
)
from s3mp.platform.domain.context import PlatformContext


class AccountAuthStore(Protocol):
    async def find_by_normalized_email(
        self, normalized_email: str
    ) -> PasswordCredential | None: ...

    async def create_account_session(
        self, user_id: UUID, token_digest: bytes, csrf_digest: bytes, expires_at: datetime
    ) -> UUID: ...

    async def resolve_account_session(self, token_digest: bytes) -> PlatformContext | None: ...

    async def revoke_account_session(self, session_id: UUID) -> None: ...

    async def account_summary(self, user_id: UUID) -> dict[str, object] | None: ...

    async def create_tenant_session(
        self,
        user_id: UUID,
        tenant_id: UUID,
        token_digest: bytes,
        csrf_digest: bytes,
        expires_at: datetime,
    ) -> bool: ...


class AccountRegistrationStore(Protocol):
    async def create_account(
        self,
        *,
        email: str,
        normalized_email: str,
        employee_number: str,
        normalized_employee_number: str,
        display_name: str,
        password_hash: str,
    ) -> dict[str, object]: ...


class AccountLoginRateLimiter(Protocol):
    async def allow(self, key: str, *, now: float | None = None) -> bool: ...


class AccountAuthenticationService:
    """Issue account and selected-tenant sessions from verified browser credentials."""

    def __init__(
        self,
        store: AccountAuthStore,
        authenticator: LocalPasswordAuthenticator,
        token_service: SessionTokenService,
        *,
        session_ttl_seconds: int,
    ) -> None:
        self._store = store
        self._authenticator = authenticator
        self._tokens = token_service
        self._ttl = timedelta(seconds=session_ttl_seconds)
        self._hasher = PasswordHasher()

    async def register(
        self, *, email: str, employee_number: str, display_name: str, password: str
    ) -> dict[str, object]:
        normalized_email = email.strip().casefold()
        normalized_employee_number = employee_number.strip().casefold()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", normalized_employee_number):
            raise ApiError(
                "validation_failed", "Employee number format is invalid", status_code=422
            )
        if not display_name.strip():
            raise ApiError("validation_failed", "Display name must not be blank", status_code=422)
        try:
            create_account = cast(AccountRegistrationStore, self._store).create_account
            return await create_account(
                email=email.strip(),
                normalized_email=normalized_email,
                employee_number=employee_number.strip(),
                normalized_employee_number=normalized_employee_number,
                display_name=display_name.strip(),
                password_hash=self._hasher.hash(password),
            )
        except IntegrityError as exc:
            raise ApiError(
                "account_already_exists", "Account identity already exists", status_code=409
            ) from exc

    async def login(
        self, identifier: str, password: str, *, rate_limit_key: str
    ) -> tuple[dict[str, object], str, str]:
        try:
            user_id = await self._authenticator.authenticate(
                identifier, password, rate_limit_key=rate_limit_key
            )
        except (AuthenticationFailed, LoginRateLimited) as exc:
            raise ApiError(
                "authentication_failed", "Invalid email or password", status_code=401
            ) from exc
        issued = self._tokens.issue()
        await self._store.create_account_session(
            user_id,
            self._tokens.digest(issued.session_token),
            self._tokens.digest(issued.csrf_token),
            datetime.now(UTC) + self._ttl,
        )
        summary = await self._store.account_summary(user_id)
        if summary is None:
            raise ApiError("authentication_failed", "Invalid email or password", status_code=401)
        return summary, issued.session_token, issued.csrf_token

    async def account_context(self, context: PlatformContext) -> dict[str, object]:
        summary = await self._store.account_summary(context.user_id)
        if summary is None:
            raise ApiError("authentication_required", "Account is not active", status_code=401)
        return {**summary, "platform_permissions": sorted(context.permissions)}

    async def logout(self, context: PlatformContext) -> None:
        await self._store.revoke_account_session(context.session_id)

    async def select_tenant(self, context: PlatformContext, tenant_id: UUID) -> tuple[str, str]:
        issued = self._tokens.issue()
        created = await self._store.create_tenant_session(
            context.user_id,
            tenant_id,
            self._tokens.digest(issued.session_token),
            self._tokens.digest(issued.csrf_token),
            datetime.now(UTC) + self._ttl,
        )
        if not created:
            raise ApiError(
                "tenant_session_denied", "Tenant access is not available", status_code=403
            )
        return issued.session_token, issued.csrf_token
