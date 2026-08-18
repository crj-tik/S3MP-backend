"""Tests for the public enum and lifecycle metadata catalog."""

from httpx import ASGITransport, AsyncClient

from _http import make_app
from s3mp.metadata.catalog import CATALOG_VERSION, STATUS_CATALOG


async def test_metadata_catalog_is_public_and_has_state_transitions() -> None:
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/metadata/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == CATALOG_VERSION
    assert payload["statuses"]["application"]
    assert payload["statuses"]["upload"]
    active = next(item for item in payload["statuses"]["application"] if item["value"] == "active")
    assert active["label"] == "正常"
    assert "suspended" in active["transitions"]
    assert payload["scopes"][-1]["value"] == "directory"
    assert {item["domain"] for item in payload["catalog"]} == {
        "identity",
        "lifecycle",
        "authorization",
        "storage",
        "file",
        "ingestion",
        "quota",
        "governance",
    }
    user_status = next(
        item
        for item in payload["catalog"]
        if item["resource"] == "user" and item["field"] == "status"
    )
    assert user_status["query_parameter"] == "status"
    assert "GET /api/v1/users" in user_status["used_by"]
    upload_status = next(
        item
        for item in payload["catalog"]
        if item["resource"] == "upload" and item["field"] == "status"
    )
    assert upload_status["query_parameter"] == "status"
    assert upload_status["used_by"] == []


async def test_metadata_catalog_can_filter_by_business_domain() -> None:
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/metadata/catalog", params=[("domains", "identity"), ("domains", "quota")]
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["domains"] == ["identity", "quota"]
    assert {item["domain"] for item in payload["catalog"]} == {"identity", "quota"}


async def test_metadata_catalog_rejects_unknown_business_domain() -> None:
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/metadata/catalog?domains=unknown")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


def test_catalog_values_are_unique_and_have_valid_transitions() -> None:
    for items in STATUS_CATALOG.values():
        values = {item["value"] for item in items}
        assert len(values) == len(items)
        for item in items:
            assert set(item["transitions"]).issubset(values)
            assert item["terminal"] is (not item["transitions"])


def test_openapi_exposes_the_same_enum_values_as_runtime_catalog() -> None:
    from s3mp.main import app

    document = app.openapi()
    operation = document["paths"]["/api/v1/metadata/catalog"]["get"]
    assert operation["operationId"] == "get_metadata_catalog"
    schemas = document["components"]["schemas"]
    for resource, items in STATUS_CATALOG.items():
        schema_name = f"Metadata{resource.title().replace('_', '')}Status"
        assert schemas[schema_name]["enum"] == [item["value"] for item in items]


def test_catalog_usage_mappings_match_openapi_query_parameters() -> None:
    from s3mp.main import app
    from s3mp.metadata.catalog import catalog_payload

    document = app.openapi()
    for descriptor in catalog_payload()["catalog"]:
        parameter = descriptor["query_parameter"]
        for used_by in descriptor["used_by"]:
            method, path = used_by.split(" ", 1)
            operation = document["paths"][path][method.lower()]
            if parameter is not None:
                names = {item["name"] for item in operation.get("parameters", [])}
                assert parameter in names, (used_by, parameter)
