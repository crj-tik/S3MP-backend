"""Write the runtime OpenAPI schema to the checked-in frontend contract."""

from __future__ import annotations

from pathlib import Path

import yaml

from s3mp.main import app

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "openapi.yaml"


def main() -> int:
    """Materialize canonical runtime documentation with stable YAML formatting."""
    with CONTRACT.open("w", encoding="utf-8", newline="\n") as stream:
        yaml.safe_dump(app.openapi(), stream, allow_unicode=True, sort_keys=False, width=100)
    print(f"Materialized runtime OpenAPI contract at {CONTRACT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
