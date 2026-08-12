## Why

The backend exposes most of the planned API surface, but the current runtime does not reliably fulfill its published contract: application creation can violate a database constraint, the runtime OpenAPI paths drift from the `/api/v1` baseline, file workflows do not complete a durable MinIO lifecycle, and local dependency verification is not reproducible. These defects affect externally visible behavior, tenant safety, and deployment readiness, so they must be corrected before the existing testing work can be accepted as an operational baseline.

## What Changes

- Repair the application creation persistence sequence so a created application and its initial owner are committed atomically and are usable through the public lifecycle API.
- Make the runtime API contract authoritative and executable: publish the runtime `/api/v1` paths, align the one-time API Key secret error code with the catalog, and enforce bidirectional OpenAPI verification.
- Complete the authenticated request boundary so protected routers receive a verified `PrincipalContext` and application services, rather than routers or fallbacks, own authorization and mutation coordination.
- Connect upload, download, multipart, copy, move, and delete workflows to MinIO/S3 with durable intent/outcome records, quota settlement, redacted audit events, and recoverable partial failures.
- Replace lossy Redis queue semantics with an acknowledged, recoverable outbox lifecycle and make rate limiting safe under concurrent requests.
- Provide one reproducible local runtime composition for PostgreSQL, Redis, and MinIO, with secret references, migration startup, dependency preflight, and separated integration-test configuration.
- Restore trustworthy quality gates for runtime code, type checking, contract checks, and infrastructure-backed tests.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `backend-application-access`: Require application lifecycle persistence and API Key secret responses to be executable and contract-aligned.
- `backend-file-storage`: Require public file workflows to perform the declared S3 lifecycle with quota, audit, and recoverable state handling.
- `backend-api-contract`: Make the published `/api/v1` baseline and registered error vocabulary match the runtime bidirectionally.
- `runtime-contract-enforcement`: Require authenticated runtime routes to be wired to application services and preserve declared mutation semantics.
- `durable-service-orchestration`: Add reliable outbox delivery and recovery requirements for externally coordinated mutations.
- `local-infrastructure-runtime`: Require a reproducible, secret-safe development composition and explicit dependency/migration readiness behavior.

## Impact

- Affected runtime modules include application repositories and services, authentication middleware and app assembly, file services and storage adapters, Redis adapters, settings, health checks, and Compose/development tooling.
- Public API behavior changes only to conform to the published contract: `/api/v1` is the canonical path base and one-time secret retrieval returns the catalogued error code.
- PostgreSQL, Redis, and MinIO are required for the full local integration profile; test configuration must not silently operate on development data.
- CI and local quality gates will run contract verification, static analysis, and infrastructure-backed tests against a single documented configuration.
