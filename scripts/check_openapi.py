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
RUNTIME_ONLY_PATHS = frozenset({"/health/live", "/health/ready"})


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
                signatures[(str(path), method.lower())] = operation
    return signatures


def response_statuses(operation: dict[str, Any]) -> set[str]:
    responses = operation.get("responses", {})
    return {str(status) for status in responses} if isinstance(responses, dict) else set()


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

    runtime_operations = operation_signatures(app.openapi())
    baseline_operations = operation_signatures(baseline)
    errors: list[str] = []
    for signature, runtime_operation in runtime_operations.items():
        if signature[0] in RUNTIME_ONLY_PATHS:
            continue
        baseline_operation = baseline_operations.get(signature)
        if baseline_operation is None:
            errors.append(
                f"Runtime operation {signature[1].upper()} {signature[0]} is absent from baseline"
            )
            continue
        missing_statuses = response_statuses(runtime_operation) - response_statuses(
            baseline_operation
        )
        if missing_statuses:
            errors.append(
                f"Baseline {signature[1].upper()} {signature[0]} lacks runtime responses "
                + ", ".join(sorted(missing_statuses))
            )
    for signature in baseline_operations:
        if signature[0] in RUNTIME_ONLY_PATHS:
            continue
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
