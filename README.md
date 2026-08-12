# S3MP Backend

Python 3.12/FastAPI backend using a root `src/s3mp` layout.

## Development

```shell
uv sync
uv run uvicorn s3mp.main:app --reload
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run python scripts/check_contracts.py
uv run python scripts/check_openapi.py
uv run alembic upgrade head --sql
```

For local PostgreSQL and Redis, copy `deploy/.env.example` to `deploy/.env`, create
`deploy/secrets/postgres_password` from the example, then run
`docker compose -f deploy/compose.yaml up --build`.

Secrets are supplied only through `S3MP_*` environment variables or mounted files using
`S3MP_*_FILE`; real secret files must not be committed.
