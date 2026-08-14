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

For local integration, `deploy/compose.yaml` starts only the API and worker and
reuses the existing PostgreSQL, Redis, and MinIO containers. Copy
`deploy/.env.example` to `deploy/.env`, configure the Docker-host URLs and
credentials there, then run `docker compose -f deploy/compose.yaml up --build`.
The optional `deploy/compose.managed-infra.yaml` retains the self-managed
PostgreSQL/Redis topology for a future isolated deployment.

Local integration configuration is supplied through untracked `deploy/.env`; real
credentials must not be committed.
