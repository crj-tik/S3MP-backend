"""S3MP FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from s3mp.applications.api.router import router as applications_router
from s3mp.applications.application.application_service import (
    ApiKeyService,
    ApplicationService,
)
from s3mp.applications.domain.credentials import ApiKeyCredentialService
from s3mp.applications.infrastructure.repositories import SqlAlchemyApplicationStore
from s3mp.authorization.api.router import router as authorization_router
from s3mp.authorization.application.management_service import AuthorizationManagementService
from s3mp.common.browser_security import BrowserCSRFMiddleware
from s3mp.common.config import Settings, get_settings
from s3mp.common.database import create_engine, create_session_factory
from s3mp.common.errors import install_error_handlers
from s3mp.common.health import router as health_router
from s3mp.common.logging import configure_logging
from s3mp.common.middleware import RequestIDMiddleware
from s3mp.common.redis import create_redis
from s3mp.files.api.router import router as files_router
from s3mp.files.application.file_service import FileApplicationService
from s3mp.files.infrastructure.authorization_repository import (
    SqlAlchemyFileAuthorizationStore,
)
from s3mp.files.infrastructure.ingestion_repository import SqlAlchemyIngestionStore
from s3mp.files.infrastructure.repositories import SqlAlchemyFileStore
from s3mp.files.infrastructure.work_signal import RedisWorkSignal
from s3mp.governance.api.router import router as governance_router
from s3mp.governance.application.governance_service import AuditService, QuotaService
from s3mp.governance.infrastructure.repositories import SqlAlchemyAuditStore, SqlAlchemyQuotaStore
from s3mp.identity.api.router import router as identity_router
from s3mp.identity.application.management_service import IdentityManagementService
from s3mp.identity.application.security import InMemoryLoginRateLimiter, LocalPasswordAuthenticator
from s3mp.platform.api.role_router import router as platform_role_router
from s3mp.platform.api.router import router as account_auth_router
from s3mp.platform.api.support_router import router as platform_support_router
from s3mp.platform.api.tenant_router import router as platform_tenant_router
from s3mp.platform.application.account_authentication import AccountAuthenticationService
from s3mp.platform.application.role_management import PlatformRoleManagementService
from s3mp.platform.application.support_access import SupportAccessService
from s3mp.platform.application.tenant_lifecycle import PlatformTenantLifecycleService
from s3mp.platform.infrastructure.rate_limiter import RedisAccountLoginRateLimiter
from s3mp.platform.infrastructure.repository import SqlAlchemyPlatformStore
from s3mp.storage.api.router import router as storage_router
from s3mp.storage.application.storage_service import StorageService
from s3mp.storage.infrastructure.minio import MinioObjectStorageAdapter
from s3mp.storage.infrastructure.repositories import SqlAlchemyStorageStore


def _known_permissions() -> frozenset[str]:
    catalog_path = Path(__file__).resolve().parents[2] / "contracts" / "permission-catalog.yaml"
    with catalog_path.open(encoding="utf-8") as stream:
        catalog = yaml.safe_load(stream) or {}
    return frozenset(
        entry["name"] for entry in catalog.get("permissions", []) if isinstance(entry, dict)
    )


def _delegable_permissions() -> frozenset[str]:
    catalog_path = Path(__file__).resolve().parents[2] / "contracts" / "permission-catalog.yaml"
    with catalog_path.open(encoding="utf-8") as stream:
        catalog = yaml.safe_load(stream) or {}
    return frozenset(
        entry["name"]
        for entry in catalog.get("permissions", [])
        if isinstance(entry, dict) and entry.get("delegable", False)
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database_url = configured.secret_value("database_url")
        redis_url = configured.secret_value("redis_url")
        engine: AsyncEngine | None = create_engine(database_url) if database_url else None
        redis: Redis | None = create_redis(redis_url) if redis_url else None
        app.state.engine = engine
        app.state.redis = redis
        session_factory = create_session_factory(engine) if engine is not None else None
        object_storage = MinioObjectStorageAdapter(configured) if configured.s3_endpoint else None
        app.state.object_storage = object_storage

        # ── Session token service ─────────────────────────────────────
        from s3mp.identity.application.security import SessionTokenService

        session_pepper = (configured.secret_value("api_key_pepper") or "p" * 32).encode()
        app.state.session_token_service = SessionTokenService(session_pepper)

        # ── Identity context provider ─────────────────────────────────
        from s3mp.identity.application.identity_provider import (
            IdentityContextProvider,
        )
        from s3mp.identity.infrastructure.identity_repository import (
            SqlAlchemyIdentityAdminStore,
        )

        class _SessionStoreAdapter:
            def __init__(self, sf: object) -> None:
                self._sf = sf

            async def find_session(self, token_digest: bytes) -> dict[str, Any] | None:
                from sqlalchemy import select

                from s3mp.identity.infrastructure.models import SessionModel

                async with self._sf() as s:  # type: ignore[operator]
                    row = await s.scalar(
                        select(SessionModel).where(SessionModel.token_digest == token_digest)
                    )
                    if row is None:
                        return None
                    return {
                        "id": row.id,
                        "tenant_id": row.tenant_id,
                        "membership_id": row.membership_id,
                        "principal_id": row.principal_id,
                        "authorization_version": row.authorization_version,
                        "expires_at": row.expires_at,
                        "revoked_at": row.revoked_at,
                    }

        if session_factory is not None:
            identity_store = SqlAlchemyIdentityAdminStore(session_factory)
            platform_store = SqlAlchemyPlatformStore(session_factory)
            app.state.platform_store = platform_store
            app.state.platform_tenant_lifecycle = PlatformTenantLifecycleService(platform_store)
            app.state.platform_role_management = PlatformRoleManagementService(platform_store)
            app.state.platform_support_access = SupportAccessService(platform_store)
            login_limiter = (
                RedisAccountLoginRateLimiter(redis)
                if redis is not None
                else InMemoryLoginRateLimiter()
            )
            app.state.account_authentication = AccountAuthenticationService(
                platform_store,
                LocalPasswordAuthenticator(platform_store, login_limiter),
                app.state.session_token_service,
                session_ttl_seconds=configured.browser_session_ttl_seconds,
            )
            app.state.identity_context_provider = IdentityContextProvider(
                session_store=_SessionStoreAdapter(session_factory),
                membership_store=identity_store,
                principal_store=identity_store,
            )
            authorization_management = AuthorizationManagementService(
                identity_store, _known_permissions(), _delegable_permissions()
            )
            app.state.authorization_management = authorization_management
            app.state.identity_management = IdentityManagementService(
                identity_store, authorization_management
            )

        async def database_check() -> None:
            if engine is None:
                raise RuntimeError("database is not configured")
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))

        async def redis_check() -> None:
            if redis is None:
                raise RuntimeError("redis is not configured")
            await redis.ping()

        async def object_storage_check() -> None:
            if object_storage is None:
                raise RuntimeError("object storage is not configured")
            await object_storage.readiness_probe()

        app.state.readiness_checks = {"database": database_check, "redis": redis_check}
        if object_storage is not None:
            app.state.readiness_checks["object_storage"] = object_storage_check

        # ── Application services ──────────────────────────────────────────
        # Registered routes receive concrete stores when database access is configured.
        class _NoopStore:
            async def _not_implemented(self, *args: object, **kwargs: object) -> object:
                raise NotImplementedError("store not wired")

            def __getattr__(self, name: str) -> object:
                return lambda *a, **kw: self._not_implemented(*a, **kw)

        _store = _NoopStore()
        application_store: Any = (
            SqlAlchemyApplicationStore(session_factory) if session_factory else _store
        )
        storage_store: Any = SqlAlchemyStorageStore(session_factory) if session_factory else _store
        app.state.application_service = ApplicationService(
            application_store, getattr(app.state, "authorization_management", None)
        )
        app.state.api_key_service = ApiKeyService(
            application_store,
            ApiKeyCredentialService(
                (configured.secret_value("api_key_pepper") or "p" * 32).encode(),
                pepper_version=configured.api_key_pepper_version,
            ),
            getattr(app.state, "authorization_management", None),
        )
        app.state.storage_service = StorageService(
            storage_store, getattr(app.state, "authorization_management", None)
        )
        file_store: Any = SqlAlchemyFileStore(session_factory) if session_factory else _store
        file_authorization_store = (
            SqlAlchemyFileAuthorizationStore(session_factory) if session_factory else None
        )
        ingestion_store = SqlAlchemyIngestionStore(session_factory) if session_factory else None
        app.state.file_service = FileApplicationService(
            file_store,
            object_storage=object_storage,
            storage_store=storage_store,
            authorization_store=file_authorization_store,
            ingestion_store=ingestion_store,
            principal_store=identity_store if session_factory else None,
            api_key_state_store=application_store if session_factory else None,
            work_notifier=RedisWorkSignal(redis) if redis is not None else None,
        )
        quota_store: Any = SqlAlchemyQuotaStore(session_factory) if session_factory else _store
        audit_store: Any = SqlAlchemyAuditStore(session_factory) if session_factory else _store
        app.state.quota_service = QuotaService(
            quota_store, getattr(app.state, "authorization_management", None)
        )
        app.state.audit_service = AuditService(
            audit_store, getattr(app.state, "authorization_management", None)
        )
        try:
            yield
        finally:
            if redis is not None:
                await redis.aclose()
            if engine is not None:
                await engine.dispose()

    configure_logging(configured.log_level)
    app = FastAPI(title="S3MP API", version="0.1.0", lifespan=lifespan)
    app.state.settings = configured
    app.state.readiness_timeout = configured.readiness_timeout_seconds
    app.state.readiness_checks = {}
    if configured.browser_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(configured.browser_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-S3MP-CSRF", "If-Match", "Idempotency-Key"],
        )
    app.add_middleware(RequestIDMiddleware)
    from s3mp.common.auth_middleware import AuthMiddleware

    app.add_middleware(AuthMiddleware)
    app.add_middleware(BrowserCSRFMiddleware)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(identity_router)
    app.include_router(account_auth_router)
    app.include_router(platform_tenant_router)
    app.include_router(platform_role_router)
    app.include_router(platform_support_router)
    app.include_router(authorization_router)
    app.include_router(applications_router)
    app.include_router(storage_router)
    app.include_router(files_router)
    app.include_router(governance_router)
    return app


app = create_app()
