"""Registration and employee-number login coverage."""

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from s3mp.common.config import Settings
from s3mp.common.errors import ApiError
from s3mp.identity.application.security import (
    InMemoryLoginRateLimiter,
    LocalPasswordAuthenticator,
    PasswordCredential,
    PasswordHasher,
    SessionTokenService,
)
from s3mp.main import create_app
from s3mp.platform.application.account_authentication import AccountAuthenticationService
from s3mp.platform.domain.context import PlatformContext


class RegistrationStore:
    def __init__(self) -> None:
        self.user_id = uuid4()
        self.password_hash = PasswordHasher().hash("correct-password")
        self.created: dict[str, object] | None = None
        self.sessions: list[UUID] = []

    async def find_by_identifier(self, identifier: str) -> PasswordCredential | None:
        if identifier in {"u@example.test", "emp-001"}:
            return PasswordCredential(self.user_id, self.password_hash)
        return None

    async def find_by_normalized_email(self, _email: str) -> PasswordCredential | None:
        return None

    async def create_account(self, **values: object) -> dict[str, object]:
        self.created = values
        return {
            "id": str(self.user_id),
            "email": values["email"],
            "employee_number": values["employee_number"],
            "display_name": values["display_name"],
        }

    async def create_account_session(
        self, user_id: UUID, _token: bytes, _csrf: bytes, _expires: datetime
    ) -> UUID:
        self.sessions.append(user_id)
        return uuid4()

    async def account_summary(self, user_id: UUID) -> dict[str, object]:
        return {
            "account": {
                "id": str(user_id),
                "email": "u@example.test",
                "employee_number": "EMP-001",
                "display_name": "User",
            },
            "tenants": [],
        }

    async def resolve_account_session(self, _digest: bytes) -> PlatformContext | None:
        return None

    async def revoke_account_session(self, _session_id: UUID) -> None:
        return None

    async def create_tenant_session(
        self,
        _user_id: UUID,
        _tenant_id: UUID,
        _token: bytes,
        _csrf: bytes,
        _expires: datetime,
    ) -> bool:
        return False


class DuplicateRegistrationStore(RegistrationStore):
    async def create_account(self, **_values: object) -> dict[str, object]:
        raise IntegrityError("duplicate", {}, Exception())


def make_service(store: RegistrationStore) -> AccountAuthenticationService:
    return AccountAuthenticationService(
        store,
        LocalPasswordAuthenticator(store, InMemoryLoginRateLimiter()),
        SessionTokenService(b"x" * 32),
        session_ttl_seconds=900,
    )


@pytest.mark.asyncio
async def test_registration_hashes_password_and_employee_number_login_works() -> None:
    store = RegistrationStore()
    service = make_service(store)

    result = await service.register(
        email="User@Example.Test",
        employee_number="EMP-001",
        display_name=" User ",
        password="correct-password",  # noqa: S106
    )
    assert "password_hash" not in result
    assert store.created is not None
    assert store.created["normalized_email"] == "user@example.test"
    assert store.created["normalized_employee_number"] == "emp-001"
    assert store.created["password_hash"] != "correct-password"  # noqa: S105

    summary, _session, _csrf = await service.login(
        "EMP-001", "correct-password", rate_limit_key="employee-login"
    )
    assert summary["account"]["employee_number"] == "EMP-001"  # type: ignore[index]


@pytest.mark.asyncio
async def test_registration_endpoint_is_public_and_returns_no_session_cookie() -> None:
    app = create_app(Settings())
    app.state.account_authentication = make_service(RegistrationStore())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/account/register",
            json={
                "email": "new@example.test",
                "employee_number": "EMP-002",
                "display_name": "New User",
                "password": "strong-password",
            },
        )

    assert response.status_code == 201
    assert "s3mp_account_session=" not in response.headers.get("set-cookie", "")
    assert "password_hash" not in response.json()


@pytest.mark.asyncio
async def test_duplicate_registration_has_stable_generic_conflict() -> None:
    service = make_service(DuplicateRegistrationStore())
    with pytest.raises(ApiError) as raised:
        await service.register(
            email="existing@example.test",
            employee_number="EMP-003",
            display_name="Existing",
            password="correct-password",  # noqa: S106
        )
    assert raised.value.code == "account_already_exists"
