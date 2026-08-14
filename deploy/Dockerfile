FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
# Installing after the source is present ensures uv installs this project into
# /app/.venv; both the API and worker import it as the `s3mp` package.
RUN uv sync --frozen --no-dev
COPY contracts ./contracts
COPY alembic.ini ./
COPY migrations ./migrations
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "s3mp.main:app", "--host", "0.0.0.0", "--port", "8000"]
