"""Idempotency-Key reuse error-envelope contract test.

The contract requires that reusing an Idempotency-Key with a different request
fingerprint returns ``409 idempotency_key_reused`` without repeating the mutation.
This test verifies the error envelope when the service layer raises that error.

NOTE: Inspection of the applications router shows ``Idempotency-Key`` is received
but not forwarded to the application service, so key-based deduplication is not
wired at the router layer today. This test simulates the service-layer enforcement
to verify the error envelope; real enforcement is tracked as a contract gap.
"""

from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from _http import make_app
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext


def _ctx() -> PrincipalContext:
    return PrincipalContext(uuid4(), uuid4(), uuid4(), 1)


class IdempotentApplicationService:
    """Fake that simulates idempotency-key reuse detection at the service layer."""

    def __init__(self) -> None:
        self.successful_creates = 0
        self._first_name: str | None = None

    async def list_apps(
        self, tenant_id: Any, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        return ([], None)

    async def get_app(self, tenant_id: Any, app_id: Any) -> dict[str, Any]:
        return {"id": str(app_id), "name": "app", "status": "active"}

    async def create_app(self, context: PrincipalContext, name: str) -> dict[str, Any]:
        if self._first_name is None:
            self._first_name = name
            self.successful_creates += 1
            return {"id": str(uuid4()), "name": name, "status": "active"}
        # Second call with a different name → simulate reuse detection.
        if name != self._first_name:
            raise ApiError(
                "idempotency_key_reused",
                "Idempotency-Key was reused with a different request body",
                status_code=409,
            )
        # Same name → idempotent replay (return the original result).
        return {"id": "replayed", "name": name, "status": "active"}

    async def update_app(self, tenant_id: Any, app_id: Any, name: str | None) -> dict[str, Any]:
        return {"id": str(app_id), "name": name or "x", "status": "active"}


async def test_idempotency_key_reuse_with_different_body_returns_409() -> None:
    svc = IdempotentApplicationService()
    app = make_app(
        {"application_service": svc, "api_key_service": object()},
        context=_ctx(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/v1/applications",
            json={"name": "app-alpha"},
            headers={"Idempotency-Key": "key-1"},
        )
        second = await client.post(
            "/api/v1/applications",
            json={"name": "app-beta"},
            headers={"Idempotency-Key": "key-1"},
        )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "idempotency_key_reused"
    assert "request_id" in second.json()
    # The mutation was not repeated — only the first create succeeded.
    assert svc.successful_creates == 1


async def test_idempotency_key_replay_with_same_body_returns_original() -> None:
    svc = IdempotentApplicationService()
    app = make_app(
        {"application_service": svc, "api_key_service": object()},
        context=_ctx(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/v1/applications",
            json={"name": "app-alpha"},
            headers={"Idempotency-Key": "key-2"},
        )
        replay = await client.post(
            "/api/v1/applications",
            json={"name": "app-alpha"},
            headers={"Idempotency-Key": "key-2"},
        )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert svc.successful_creates == 1
