"""Runtime contract coverage: compare declared OpenAPI ops with FastAPI OpenAPI schema."""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "contracts" / "openapi.yaml"
SKIP_PATHS = frozenset(
    {"/health/live", "/health/ready", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
)


def main() -> int:
    if not BASELINE.is_file():
        print("contracts/openapi.yaml is missing", file=sys.stderr)
        return 1
    with BASELINE.open(encoding="utf-8") as f:
        baseline = yaml.safe_load(f)

    from s3mp.common.config import Settings
    from s3mp.main import create_app

    runtime = create_app(Settings()).openapi()

    declared = set()
    for path, item in (baseline.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method in item:
            if method.lower() in {"get", "put", "post", "delete", "options", "head", "patch"}:
                declared.add((method.lower(), path))

    runtime_ops = set()
    for path, item in (runtime.get("paths") or {}).items():
        if path in SKIP_PATHS:
            continue
        if not isinstance(item, dict):
            continue
        for method in item:
            if method.lower() in {"get", "put", "post", "delete", "options", "head", "patch"}:
                runtime_ops.add((method.lower(), path))

    missing = declared - runtime_ops
    extra = runtime_ops - declared

    if missing or extra:
        for m, p in sorted(missing):
            print(f"MISSING  {m.upper():7s} {p}")
        for m, p in sorted(extra):
            print(f"EXTRA    {m.upper():7s} {p}")
        print(
            "\nCoverage: "
            f"{len(declared) - len(missing)}/{len(declared)} declared routes implemented",
            file=sys.stderr,
        )
        return 1

    print(f"Contract coverage: {len(declared)}/{len(declared)} declared routes implemented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
