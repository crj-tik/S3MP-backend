"""Shared HTTP test helpers for fake-service contract tests.

Not a conftest — a plain module of helper functions. Fakes remain locally
defined per test file; only the generic app/client wiring is shared.
"""

from __future__ import annotations

from typing import Any

from s3mp.common.config import Settings
from s3mp.identity.domain.context import PrincipalContext
from s3mp.main import create_app


class AllowAllAuthorizationManagement:
    """Explicit authorization double for router tests with injected contexts."""

    async def require_permission(self, context: PrincipalContext, permission: str) -> None:
        return None


def make_app(
    services: dict[str, Any] | None = None,
    *,
    context: PrincipalContext | None = None,
    settings: Settings | None = None,
) -> Any:
    """Build an app with fake services injected and an optional PrincipalContext.

    When ``context`` is None no auth middleware is installed, so authenticated
    endpoints raise 401 — use this to assert the unauthenticated failure path.
    """
    app = create_app(settings or Settings())
    for name, svc in (services or {}).items():
        setattr(app.state, name, svc)
    if context is not None:
        if "authorization_management" not in (services or {}):
            app.state.authorization_management = AllowAllAuthorizationManagement()

        @app.middleware("http")
        async def _inject(request: Any, call_next: Any) -> Any:
            request.state.principal_context = context
            return await call_next(request)

    return app
