"""HTTP boundary tests for account cookies, CSRF and tenant-context separation."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from s3mp.common.config import Settings
from s3mp.identity.application.security import SessionTokenService
from s3mp.identity.domain.context import PrincipalContext
from s3mp.main import create_app
from s3mp.platform.domain.context import PlatformContext


class AccountService:
    async def login(
        self, email: str, password: str, *, rate_limit_key: str
    ) -> tuple[dict[str, object], str, str]:
        expected_password = "valid"  # noqa: S105 - deterministic test credential
        if password != expected_password:
            from s3mp.common.errors import ApiError

            raise ApiError("authentication_failed", "Invalid email or password", 401)
        return (
            {"account": {"id": "user", "email": email, "display_name": "User"}, "tenants": []},
            "opaque",
            "csrf",
        )

    async def account_context(self, _context: PlatformContext) -> dict[str, object]:
        return {
            "account": {"id": "user", "email": "u@example.test", "display_name": "User"},
            "tenants": [],
        }

    async def logout(self, _context: PlatformContext) -> None:
        return None

    async def select_tenant(self, _context: PlatformContext, _tenant_id: object) -> tuple[str, str]:
        return "tenant-opaque", "tenant-csrf"


class DenyingTenantAccountService(AccountService):
    async def select_tenant(self, _context: PlatformContext, _tenant_id: object) -> tuple[str, str]:
        from s3mp.common.errors import ApiError

        raise ApiError("tenant_session_denied", "Tenant access is not available", 403)


def app_with_account_context(*, secure: bool = False) -> Any:
    app = create_app(Settings(browser_cookie_secure=secure))
    app.state.account_authentication = AccountService()
    app.state.session_token_service = SessionTokenService(b"x" * 32)

    @app.middleware("http")
    async def inject_context(request: Any, call_next: Any) -> Any:
        request.state.principal_context = PrincipalContext(uuid4(), uuid4(), uuid4(), 1)
        request.state.platform_context = PlatformContext(uuid4(), uuid4(), frozenset())
        return await call_next(request)

    return app


@pytest.mark.asyncio
async def test_login_failure_is_uniform_and_success_sets_opaque_cookie_attributes() -> None:
    app = app_with_account_context()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bad_one = await client.post(
            "/api/v1/auth/login", json={"email": "unknown@test", "password": "bad"}
        )
        bad_two = await client.post(
            "/api/v1/auth/login", json={"email": "known@test", "password": "bad"}
        )
        success = await client.post(
            "/api/v1/auth/login", json={"email": "known@test", "password": "valid"}
        )

    assert (bad_one.status_code, bad_one.json()["code"]) == (401, "authentication_failed")
    assert (bad_two.status_code, bad_two.json()["code"]) == (401, "authentication_failed")
    assert "opaque" not in success.text
    assert "HttpOnly" in success.headers["set-cookie"]
    assert "s3mp_account_session=" in success.headers["set-cookie"]
    assert "Secure" not in success.headers["set-cookie"]


@pytest.mark.asyncio
async def test_csrf_rejects_browser_logout_without_matching_header() -> None:
    app = app_with_account_context()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("s3mp_account_session", "opaque")
        client.cookies.set("s3mp_account_csrf", "csrf")
        response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_validation_failed"


@pytest.mark.asyncio
async def test_logout_with_csrf_revokes_account_session_and_clears_cookies() -> None:
    app = app_with_account_context()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("s3mp_account_session", "opaque")
        client.cookies.set("s3mp_account_csrf", "csrf")
        response = await client.post("/api/v1/auth/logout", headers={"X-S3MP-CSRF": "csrf"})

    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_tenant_selection_denial_does_not_issue_tenant_cookie() -> None:
    app = app_with_account_context()
    app.state.account_authentication = DenyingTenantAccountService()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("s3mp_account_session", "opaque")
        client.cookies.set("s3mp_account_csrf", "csrf")
        response = await client.post(
            "/api/v1/auth/tenant-sessions",
            json={"tenant_id": str(uuid4())},
            headers={"X-S3MP-CSRF": "csrf"},
        )

    assert (response.status_code, response.json()["code"]) == (403, "tenant_session_denied")
    assert "s3mp_session=" not in response.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_account_only_context_cannot_access_tenant_me_endpoint() -> None:
    app = create_app(Settings())
    app.state.session_token_service = SessionTokenService(b"x" * 32)

    class PlatformStore:
        async def resolve_account_session(self, _digest: bytes) -> PlatformContext:
            return PlatformContext(uuid4(), uuid4(), frozenset({"platform.tenants.read"}))

    app.state.platform_store = PlatformStore()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("s3mp_account_session", "account-only")
        response = await client.get("/api/v1/me")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


@pytest.mark.asyncio
async def test_platform_account_cannot_access_tenant_file_or_application_management() -> None:
    app = create_app(Settings())
    app.state.session_token_service = SessionTokenService(b"x" * 32)

    class PlatformStore:
        async def resolve_account_session(self, _digest: bytes) -> PlatformContext:
            return PlatformContext(uuid4(), uuid4(), frozenset({"platform.tenants.manage"}))

    app.state.platform_store = PlatformStore()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("s3mp_account_session", "account-only")
        files = await client.get(f"/api/v1/storage_spaces/{uuid4()}/files")
        applications = await client.get("/api/v1/applications")
        storage_connections = await client.get("/api/v1/storage_connections")
        api_keys = await client.get(f"/api/v1/applications/{uuid4()}/api_keys")

    responses = (files, applications, storage_connections, api_keys)
    assert all(response.status_code == 401 for response in responses)
    assert all(response.json()["code"] == "authentication_required" for response in responses)


@pytest.mark.asyncio
async def test_platform_account_cannot_manage_tenant_lifecycle_routes() -> None:
    app = create_app(Settings())
    app.state.session_token_service = SessionTokenService(b"x" * 32)

    class PlatformStore:
        async def resolve_account_session(self, _digest: bytes) -> PlatformContext:
            return PlatformContext(uuid4(), uuid4(), frozenset({"platform.tenants.manage"}))

    app.state.platform_store = PlatformStore()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("s3mp_account_session", "account-only")
        response = await client.get(f"/api/v1/applications/{uuid4()}")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


@pytest.mark.asyncio
async def test_cors_uses_exact_development_origin_with_credentials() -> None:
    app = create_app(Settings(browser_origins=("http://localhost:5173",)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
        )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cookie_and_cors_configuration_reject_insecure_production_values(tmp_path: Path) -> None:
    secret_files: list[Path] = []
    for name in ("database_url", "redis_url", "api_key_pepper"):
        path = tmp_path / name
        path.write_text("x" * 32, encoding="utf-8")
        secret_files.append(path)
    with pytest.raises(ValidationError, match="browser cookies must be secure"):
        Settings(
            environment="production",
            browser_cookie_secure=False,
            database_url_file=secret_files[0],
            redis_url_file=secret_files[1],
            api_key_pepper_file=secret_files[2],
        )
    with pytest.raises(ValidationError, match="wildcard origins"):
        Settings(browser_origins=("*",))
