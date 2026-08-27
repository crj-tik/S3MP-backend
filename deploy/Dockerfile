FROM python:3.12-slim
# Keep local and production images independent from ghcr.io, whose metadata
# requests can fail before Docker starts the actual build.
RUN python -m pip install --no-cache-dir "uv>=0.7,<0.8"
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
# Installing after the source is present ensures uv installs this project into
# /app/.venv; both the API and worker import it as the `s3mp` package.
RUN uv sync --frozen --no-dev
COPY scripts ./scripts
COPY contracts ./contracts
COPY alembic.ini ./
COPY migrations ./migrations
COPY deploy/entrypoint.sh /usr/local/bin/s3mp-entrypoint
RUN chmod +x /usr/local/bin/s3mp-entrypoint
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["/usr/local/bin/s3mp-entrypoint"]
CMD ["uvicorn", "s3mp.main:app", "--host", "0.0.0.0", "--port", "8000"]
