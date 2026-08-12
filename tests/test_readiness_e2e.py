"""Readiness endpoint end-to-end test with real docker-deployed services.

Uses ``app.router.lifespan_context`` to run the FastAPI lifespan inside the
pytest-asyncio event loop (avoiding TestClient's portal, which is incompatible
with asyncpg connection pooling). This populates ``app.state.readiness_checks``
with real database/redis/object-storage checks before the request is sent.
"""

from httpx import ASGITransport, AsyncClient

from _infrastructure import real_settings
from s3mp.main import create_app


async def test_readiness_returns_200_when_all_dependencies_healthy() -> None:
    app = create_app(real_settings())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    checks = body["checks"]
    assert checks.get("database") == "ok"
    assert checks.get("redis") == "ok"
    assert checks.get("object_storage") == "ok"


async def test_liveness_always_returns_200() -> None:
    app = create_app(real_settings())
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
