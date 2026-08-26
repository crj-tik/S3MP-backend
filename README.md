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

For local integration, `deploy/compose.yaml` starts PostgreSQL, Redis, the
database migration job, API, worker, and scheduler as one isolated stack.
PostgreSQL and Redis use named Docker volumes and are not published to host
ports. Copy `deploy/.env.example` to `deploy/.env`, configure passwords and S3
credentials there, then run `docker compose -f deploy/compose.yaml up --build`.

Local integration configuration is supplied through untracked `deploy/.env`; real
credentials must not be committed.
