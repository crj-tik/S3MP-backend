from fastapi.testclient import TestClient

from s3mp.common.config import Settings
from s3mp.main import create_app


def test_liveness_and_request_id() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(response.headers["x-request-id"]) == 32


def test_readiness_fails_without_dependencies() -> None:
    with TestClient(create_app(Settings())) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "unavailable", "redis": "unavailable"}
