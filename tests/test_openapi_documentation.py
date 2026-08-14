"""Regression tests for Chinese Swagger and checked-in contract documentation."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from s3mp.main import app

ROOT = Path(__file__).resolve().parents[1]
HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def _contains_chinese(value: object) -> bool:
    return isinstance(value, str) and any("\u4e00" <= character <= "\u9fff" for character in value)


def _walk_properties(value: Any, descriptions: dict[str, set[str]]) -> None:
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            for name, property_schema in properties.items():
                assert isinstance(property_schema, dict)
                description = property_schema.get("description")
                assert _contains_chinese(description), (
                    f"property {name!r} lacks Chinese description"
                )
                descriptions[str(name)].add(str(description))
        for nested in value.values():
            _walk_properties(nested, descriptions)
    elif isinstance(value, list):
        for nested in value:
            _walk_properties(nested, descriptions)


def test_every_public_swagger_input_and_property_has_chinese_description() -> None:
    schema = app.openapi()
    property_descriptions: dict[str, set[str]] = defaultdict(set)
    parameter_descriptions: dict[tuple[str, str], set[str]] = defaultdict(set)

    for path, path_item in schema["paths"].items():
        assert isinstance(path_item, dict)
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            assert isinstance(operation, dict)
            assert _contains_chinese(operation.get("description")), f"{method.upper()} {path}"
            for parameter in operation.get("parameters", []):
                assert isinstance(parameter, dict)
                description = parameter.get("description")
                assert _contains_chinese(description), (
                    f"{method.upper()} {path} {parameter.get('name')}"
                )
                parameter_descriptions[(str(parameter["in"]), str(parameter["name"]))].add(
                    str(description)
                )

    _walk_properties(schema, property_descriptions)
    assert all(len(descriptions) == 1 for descriptions in property_descriptions.values())
    assert all(len(descriptions) == 1 for descriptions in parameter_descriptions.values())


def test_published_contract_equals_runtime_swagger_schema() -> None:
    with (ROOT / "contracts" / "openapi.yaml").open(encoding="utf-8") as stream:
        contract = yaml.safe_load(stream)

    assert contract == app.openapi()
