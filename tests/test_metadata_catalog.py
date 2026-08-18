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
    active = next(item for item in payload["statuses"]["application"] if item["value"] == "active")
    assert active["label"] == "正常"
    assert "suspended" in active["transitions"]
    assert payload["scopes"][-1]["value"] == "directory"


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
