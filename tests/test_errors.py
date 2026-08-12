from uuid import uuid4

from fastapi import APIRouter, Query
from fastapi.testclient import TestClient

from s3mp.common.config import Settings
from s3mp.common.errors import ApiError
from s3mp.identity.domain.context import PrincipalContext
from s3mp.main import create_app


def _authenticated_app() -> object:
    app = create_app(Settings())

    @app.middleware("http")
    async def inject_context(request: object, call_next: object) -> object:
        request.state.principal_context = PrincipalContext(uuid4(), uuid4(), uuid4(), 1)  # type: ignore[attr-defined,union-attr]
        return await call_next(request)  # type: ignore[misc]

    return app


def test_stable_api_error_includes_request_id() -> None:
    app = _authenticated_app()
    router = APIRouter()

    @router.get("/failure")
    async def failure() -> None:
        raise ApiError("conflict", "Conflict", 409, {"field": "name"})

    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/failure")
    assert response.status_code == 409
    assert response.json() == {
        "code": "conflict",
        "message": "Conflict",
        "request_id": response.headers["x-request-id"],
        "details": {"field": "name"},
    }


def test_validation_error_is_json_serializable() -> None:
    app = _authenticated_app()
    router = APIRouter()

    @router.get("/validated")
    async def validated(value: int = Query(gt=0)) -> dict[str, int]:
        return {"value": value}

    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/validated", params={"value": "invalid"})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_not_found_and_method_not_allowed_use_stable_envelope() -> None:
    with TestClient(_authenticated_app()) as client:
        not_found = client.get("/missing")
        method_not_allowed = client.post("/health/live")
    assert not_found.status_code == 404
    assert not_found.json()["code"] == "resource_not_found"
    assert not_found.json()["request_id"] == not_found.headers["x-request-id"]
    assert method_not_allowed.status_code == 405
    assert method_not_allowed.json()["code"] == "method_not_allowed"
