"""Verify implemented runtime operations remain compatible with the contract baseline."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from s3mp.main import app

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "contracts" / "openapi.yaml"
HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
# FastAPI auto-generates 422 for any endpoint with validation (path/query/body params).
# It is not a meaningful contract difference — exclude it from comparison.
IGNORED_RESPONSE_STATUSES = frozenset({"422"})


def operation_signatures(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    signatures: dict[tuple[str, str], dict[str, Any]] = {}
    paths = document.get("paths", {})
    if not isinstance(paths, dict):
        return signatures
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() in HTTP_METHODS and isinstance(operation, dict):
                merged_operation = dict(operation)
                merged_operation["parameters"] = [
                    *path_item.get("parameters", []),
                    *operation.get("parameters", []),
                ]
                signatures[(str(path), method.lower())] = merged_operation
    return signatures


def response_statuses(operation: dict[str, Any]) -> set[str]:
    responses = operation.get("responses", {})
    return {str(status) for status in responses} if isinstance(responses, dict) else set()


def _resolve(document: dict[str, Any], value: Any) -> dict[str, Any]:
    """Resolve local component references used by parameters and request bodies."""
    while isinstance(value, dict) and isinstance(value.get("$ref"), str):
        reference = value["$ref"]
        if not reference.startswith("#/"):
            break
        target: Any = document
        for part in reference[2:].split("/"):
            if not isinstance(target, dict) or part not in target:
                return {}
            target = target[part]
        if not isinstance(target, dict):
            return {}
        value = target
    return value if isinstance(value, dict) else {}


def _operation_parameters(
    document: dict[str, Any], operation: dict[str, Any]
) -> set[tuple[str, str, str]]:
    """Return declared parameter identities.

    Idempotency and precondition headers deliberately stay optional in FastAPI
    parsing so the application can return its registered 400 error envelope
    rather than framework-generated 422 responses. Their business-required
    semantics are exercised by HTTP tests, while this check ensures both
    documents expose the same parameter names and locations.
    """
    parameters: set[tuple[str, str, str]] = set()
    for raw_parameter in operation.get("parameters", []):
        parameter = _resolve(document, raw_parameter)
        name, location = parameter.get("name"), parameter.get("in")
        description = parameter.get("description")
        if isinstance(name, str) and isinstance(location, str):
            parameters.add((name, location, description if isinstance(description, str) else ""))
    return parameters


def _request_body_media_types(
    document: dict[str, Any], operation: dict[str, Any]
) -> tuple[bool, set[str]]:
    raw_body = operation.get("requestBody")
    if raw_body is None:
        return False, set()
    body = _resolve(document, raw_body)
    content = body.get("content", {})
    return bool(body.get("required")), set(content) if isinstance(content, dict) else set()


def _response_schemas(
    document: dict[str, Any], operation: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for status, response in operation.get("responses", {}).items():
        if str(status) in IGNORED_RESPONSE_STATUSES:
            continue
        resolved_response = _resolve(document, response)
        content = resolved_response.get("content", {})
        if not isinstance(content, dict):
            continue
        json_content = content.get("application/json")
        if isinstance(json_content, dict) and isinstance(json_content.get("schema"), dict):
            schemas[str(status)] = _normalise_schema(document, json_content["schema"])
    return schemas


def _request_schemas(document: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    raw_body = operation.get("requestBody")
    if raw_body is None:
        return {}
    body = _resolve(document, raw_body)
    content = body.get("content", {})
    if not isinstance(content, dict):
        return {}
    return {
        media_type: _normalise_schema(document, value["schema"])
        for media_type, value in content.items()
        if isinstance(value, dict) and isinstance(value.get("schema"), dict)
    }


def _normalise_schema(document: dict[str, Any], value: Any) -> dict[str, Any]:
    """Expand local references and drop generator-only schema metadata."""
    resolved = _resolve(document, value)
    result: dict[str, Any] = {}
    for key, item in resolved.items():
        if key in {"title", "examples", "example", "default", "pattern"}:
            continue
        if key == "properties" and isinstance(item, dict):
            result[key] = {
                name: _normalise_schema(document, child) for name, child in sorted(item.items())
            }
        elif key == "items" and isinstance(item, dict):
            result[key] = _normalise_schema(document, item)
        elif key in {"allOf", "anyOf", "oneOf"} and isinstance(item, list):
            result[key] = [_normalise_schema(document, child) for child in item]
        elif isinstance(item, dict):
            result[key] = _normalise_schema(document, item)
        elif isinstance(item, list):
            result[key] = sorted(item) if key in {"required", "enum"} else item
        else:
            result[key] = (
                int(item)
                if key in {"minimum", "maximum"} and isinstance(item, float) and item.is_integer()
                else item
            )
    all_of = result.pop("allOf", None)
    if isinstance(all_of, list) and all(isinstance(entry, dict) for entry in all_of):
        merged: dict[str, Any] = {}
        for entry in all_of:
            incoming_required = entry.pop("required", [])
            merged.update({key: value for key, value in entry.items() if key != "properties"})
            if "properties" in entry:
                merged.setdefault("properties", {}).update(entry["properties"])
            if incoming_required:
                merged.setdefault("required", []).extend(incoming_required)
        if "required" in merged:
            merged["required"] = sorted(set(merged["required"]))
        result = merged
    nullable = result.get("anyOf")
    if (
        isinstance(nullable, list)
        and len(nullable) == 2
        and {entry.get("type") for entry in nullable} == {"string", "null"}
    ):
        return {"type": ["string", "null"]}
    if result.get("format") == "uuid":
        result.pop("format")
    return result


def main() -> int:
    if not BASELINE.is_file():
        print("Required contracts/openapi.yaml baseline is missing", file=sys.stderr)
        return 1
    try:
        with BASELINE.open(encoding="utf-8") as stream:
            baseline = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        print(f"Unable to parse contracts/openapi.yaml: {exc}", file=sys.stderr)
        return 1
    if not isinstance(baseline, dict):
        print("contracts/openapi.yaml must contain an object", file=sys.stderr)
        return 1

    runtime = app.openapi()
    runtime_operations = operation_signatures(runtime)
    baseline_operations = operation_signatures(baseline)
    errors: list[str] = []
    for signature, runtime_operation in runtime_operations.items():
        baseline_operation = baseline_operations.get(signature)
        if baseline_operation is None:
            errors.append(
                f"Runtime operation {signature[1].upper()} {signature[0]} is absent from baseline"
            )
            continue
        missing_statuses = (
            response_statuses(runtime_operation)
            - response_statuses(baseline_operation)
            - IGNORED_RESPONSE_STATUSES
        )
        if missing_statuses:
            errors.append(
                f"Baseline {signature[1].upper()} {signature[0]} lacks runtime responses "
                + ", ".join(sorted(missing_statuses))
            )
        for metadata in ("summary", "description"):
            if runtime_operation.get(metadata) != baseline_operation.get(metadata):
                errors.append(
                    f"{metadata.capitalize()} differs for {signature[1].upper()} {signature[0]}"
                )
        baseline_parameters = _operation_parameters(baseline, baseline_operation)
        runtime_parameters = _operation_parameters(runtime, runtime_operation)
        if baseline_parameters != runtime_parameters:
            errors.append(f"Parameter contract differs for {signature[1].upper()} {signature[0]}")
        baseline_body = _request_body_media_types(baseline, baseline_operation)
        runtime_body = _request_body_media_types(runtime, runtime_operation)
        if baseline_body != runtime_body:
            errors.append(
                f"Request body contract differs for {signature[1].upper()} {signature[0]}"
            )
        baseline_schemas = _response_schemas(baseline, baseline_operation)
        runtime_schemas = _response_schemas(runtime, runtime_operation)
        for status in sorted(set(baseline_schemas) | set(runtime_schemas)):
            if baseline_schemas.get(status) != runtime_schemas.get(status):
                errors.append(
                    f"Response schema differs for {signature[1].upper()} {signature[0]} {status}"
                )
        if _request_schemas(baseline, baseline_operation) != _request_schemas(
            runtime, runtime_operation
        ):
            errors.append(f"Request schema differs for {signature[1].upper()} {signature[0]}")
    for signature in baseline_operations:
        if signature not in runtime_operations:
            errors.append(
                f"Baseline operation {signature[1].upper()} {signature[0]} is absent from runtime"
            )
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Validated {len(runtime_operations)} runtime operations against contract baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
