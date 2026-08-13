"""Validate contract files when the backend-owned contracts directory is present."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
REQUIRED = ("openapi.yaml", "error-codes.yaml", "permission-catalog.yaml")


def load_document(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        if path.suffix == ".json":
            return json.load(stream)
        return yaml.safe_load(stream)


def validate_openapi(document: Any) -> list[str]:
    if not isinstance(document, dict):
        return ["openapi.yaml must contain an object"]
    errors = []
    if not str(document.get("openapi", "")).startswith("3."):
        errors.append("openapi.yaml must declare OpenAPI 3.x")
    if not isinstance(document.get("info"), dict):
        errors.append("openapi.yaml must contain info")
    if not isinstance(document.get("paths"), dict):
        errors.append("openapi.yaml must contain paths")
    return errors


def catalog_entries(document: Any, candidates: tuple[str, ...]) -> list[Any] | None:
    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        for candidate in candidates:
            entries = document.get(candidate)
            if isinstance(entries, list):
                return list(entries)
    return None


def catalog_identifiers(document: Any, candidates: tuple[str, ...]) -> set[str]:
    entries = catalog_entries(document, candidates) or []
    return {
        str(
            entry
            if isinstance(entry, str)
            else entry.get("code") or entry.get("name") or entry.get("id")
        )
        for entry in entries
        if isinstance(entry, str | dict)
    }


def collect_key_values(document: Any, key: str) -> set[str]:
    values: set[str] = set()
    if isinstance(document, dict):
        for item_key, value in document.items():
            if item_key == key and isinstance(value, str):
                values.add(value)
            values.update(collect_key_values(value, key))
    elif isinstance(document, list):
        for value in document:
            values.update(collect_key_values(value, key))
    return values


def collect_example_error_codes(contracts: Path) -> set[str]:
    codes: set[str] = set()
    examples = contracts / "examples"
    if examples.is_dir():
        for path in examples.iterdir():
            if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
                continue
            document = load_document(path)
            if isinstance(document, dict):
                value = document.get("value", document)
                if isinstance(value, dict) and isinstance(value.get("code"), str):
                    codes.add(value["code"])
    return codes


def validate_catalog(path: Path, candidates: tuple[str, ...]) -> list[str]:
    document = load_document(path)
    entries = catalog_entries(document, candidates)
    if entries is None:
        return [f"{path.name} must contain a list catalog"]
    errors = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if isinstance(entry, str):
            identifier = entry
        elif isinstance(entry, dict):
            identifier = str(entry.get("code") or entry.get("name") or entry.get("id") or "")
        else:
            identifier = ""
        if not identifier:
            errors.append(f"{path.name} entry {index} needs code/name/id")
        elif identifier in seen:
            errors.append(f"{path.name} contains duplicate {identifier}")
        seen.add(identifier)
    return errors


def validate_operation_permission_classifications(openapi: Any) -> list[str]:
    """Verify every permissioned OpenAPI operation has a runtime classification."""
    from s3mp.common.api.dependencies import OPERATION_PERMISSION_CLASSIFICATIONS

    operations: dict[str, str] = {}
    for path_item in (openapi.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            permission = operation.get("x-permission")
            if isinstance(operation_id, str) and isinstance(permission, str):
                operations[operation_id] = permission if isinstance(permission, str) else ""
    errors = []
    missing = set(operations) - set(OPERATION_PERMISSION_CLASSIFICATIONS)
    if missing:
        errors.append("Permissioned operations missing runtime classification: " + ", ".join(sorted(missing)))
    stale = set(OPERATION_PERMISSION_CLASSIFICATIONS) - set(operations)
    if stale:
        errors.append("Runtime classifications missing from OpenAPI: " + ", ".join(sorted(stale)))
    for operation_id, permission in operations.items():
        runtime_permission = OPERATION_PERMISSION_CLASSIFICATIONS.get(operation_id)
        if runtime_permission is not None and permission != runtime_permission:
            errors.append(
                f"Permission mismatch for {operation_id}: "
                f"OpenAPI={permission!r}, runtime={runtime_permission!r}"
            )
    return errors


def validate_management_route_enforcement() -> list[str]:
    """Verify each classified management operation has its permission dependency."""
    from s3mp.common.api.dependencies import MANAGEMENT_OPERATION_PERMISSIONS
    from s3mp.main import app

    def walk(routes: Any) -> list[Any]:
        flattened: list[Any] = []
        for route in routes:
            nested = getattr(route, "routes", None)
            if nested is None:
                original_router = getattr(route, "original_router", None)
                nested = getattr(original_router, "routes", None)
            if nested is not None:
                flattened.extend(walk(nested))
            else:
                flattened.append(route)
        return flattened

    bound_operations: dict[str, str] = {}
    for route in walk(app.routes):
        operation_id = getattr(route, "operation_id", None)
        if not isinstance(operation_id, str) or operation_id not in MANAGEMENT_OPERATION_PERMISSIONS:
            continue
        dependencies = getattr(getattr(route, "dependant", None), "dependencies", ())
        dependency_operations = {
            getattr(dependency.call, "__s3mp_management_operation_id__", None)
            for dependency in dependencies
            if getattr(dependency, "call", None) is not None
        }
        if operation_id in dependency_operations:
            bound_operations[operation_id] = MANAGEMENT_OPERATION_PERMISSIONS[operation_id]

    missing = set(MANAGEMENT_OPERATION_PERMISSIONS) - set(bound_operations)
    if missing:
        return [
            "Management operations missing runtime permission dependency: "
            + ", ".join(sorted(missing))
        ]
    return []


def main() -> int:
    if not CONTRACTS.exists():
        print("contracts/ is absent; contract validation deferred")
        return 0
    missing = [name for name in REQUIRED if not (CONTRACTS / name).is_file()]
    if missing:
        print("Missing contract files: " + ", ".join(missing), file=sys.stderr)
        return 1
    try:
        openapi = load_document(CONTRACTS / "openapi.yaml")
        error_catalog = load_document(CONTRACTS / "error-codes.yaml")
        permission_catalog = load_document(CONTRACTS / "permission-catalog.yaml")
        errors = validate_openapi(openapi)
        errors += validate_catalog(CONTRACTS / "error-codes.yaml", ("errors", "error_codes"))
        errors += validate_catalog(
            CONTRACTS / "permission-catalog.yaml", ("permissions", "operations")
        )
        errors += validate_operation_permission_classifications(openapi)
        errors += validate_management_route_enforcement()
        known_permissions = catalog_identifiers(permission_catalog, ("permissions", "operations"))
        referenced_permissions = collect_key_values(openapi, "x-permission")
        unknown_permissions = referenced_permissions - known_permissions
        if unknown_permissions:
            errors.append(
                "OpenAPI references unknown permissions: " + ", ".join(sorted(unknown_permissions))
            )
        known_errors = catalog_identifiers(error_catalog, ("errors", "error_codes"))
        referenced_errors = collect_key_values(openapi, "x-error-code")
        referenced_errors.update(collect_example_error_codes(CONTRACTS))
        unknown_errors = referenced_errors - known_errors
        if unknown_errors:
            errors.append(
                "OpenAPI/examples reference unknown error codes: "
                + ", ".join(sorted(unknown_errors))
            )
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"Unable to parse contracts: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Contract structure, error codes, and permission catalog are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
