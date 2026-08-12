## Why

The previous contract-surface change was archived while its implementation plan still contained uncompleted service, persistence, S3 coordination, and verification work. Several runtime routes can therefore reach placeholder stores or only partially implemented workflows, risking tenant-boundary, audit, and recovery failures.

## What Changes

- Replace every remaining placeholder application service/store with tenant-scoped SQLAlchemy repositories and explicit composition-root wiring.
- Complete identity/authorization, application/API key, storage/file, upload/multipart/object-operation, quota, and audit service workflows.
- Make the local MinIO-compatible S3 adapter the executable development/integration target, including safe capability checks and recovery scenarios.
- Enforce idempotency, ETag, authorization, audit-before-success, and outbox/reconciliation behavior across mutating workflows.
- Add service, repository, HTTP contract, and MinIO integration coverage for the declared API surface.

## Capabilities

### New Capabilities

- `durable-service-orchestration`: Cross-resource persistence, outbox/reconciliation, and high-risk audit coordination for application services.

### Modified Capabilities

- `backend-api-contract`: Runtime endpoints gain complete, contract-verified service implementations.
- `backend-application-access`: Application and API Key workflows gain durable tenant-scoped persistence, lifecycle enforcement, and audit coordination.
- `backend-file-storage`: File, upload, multipart, object-operation, quota, and MinIO workflows gain executable recovery and verification behavior.
- `backend-identity-authorization`: Identity and authorization endpoints gain complete tenant-scoped service and repository implementations.
- `runtime-contract-enforcement`: All registered routes gain validated service wiring and mutation-policy enforcement.

## Impact

- Affects `src/s3mp/**`, `migrations/**`, `tests/**`, and local development configuration.
- Uses PostgreSQL/SQLAlchemy, Redis where idempotency or worker coordination requires it, and the local MinIO S3-compatible service for development/integration tests.
- Preserves published `/api/v1` paths and response contracts; no browser-visible storage credentials are introduced.
