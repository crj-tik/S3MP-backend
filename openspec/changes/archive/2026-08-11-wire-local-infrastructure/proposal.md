## Why

Local MinIO, PostgreSQL, and Redis containers are deployed, but the backend deployment profile does not yet wire all three components into a verified runtime configuration or use Redis for its declared coordination responsibilities.

## What Changes

- Add a development infrastructure profile that supplies MinIO connection and secret references to the API without embedding credential values in source or Compose files.
- Make API startup/readiness validate PostgreSQL, Redis, and MinIO together and document host-versus-container endpoint resolution.
- Provide Redis-backed adapters for idempotency, rate limiting, and outbox coordination, with explicit fallback boundaries for tests only.
- Run migrations as a controlled deployment step before API readiness is accepted.

## Capabilities

### New Capabilities

- `local-infrastructure-runtime`: Verified local runtime integration of PostgreSQL, Redis, and MinIO for API development and integration testing.

### Modified Capabilities

- `backend-file-storage`: Development object-storage configuration and readiness become executable through the deployed MinIO service.
- `runtime-contract-enforcement`: Idempotency and runtime readiness behavior use durable runtime dependencies.

## Impact

- Affects `deploy/**`, `local-s3/**`, `src/s3mp/common/**`, composition-root wiring, and integration tests.
- Preserves the independent local MinIO container while enabling explicit API connection configuration for host and Docker-network execution.
