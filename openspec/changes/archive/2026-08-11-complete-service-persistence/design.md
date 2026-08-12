## Context

See proposal.md. The codebase has domain models and router shells, but some services are still wired to a placeholder store and cross-system workflows lack durable reconciliation.

## Goals / Non-Goals

**Goals:**
- Use typed application services with tenant-scoped SQLAlchemy repositories.
- Make object-storage mutations recoverable across database, MinIO, quota, and audit state.
- Verify every public route through service and HTTP tests.

**Non-Goals:**
- Change published endpoint paths or expose S3 credentials to clients.
- Treat database and S3 operations as a distributed transaction.

## Decisions

### 1. Composition root owns concrete adapters

FastAPI lifespan constructs session factories, repositories, Redis-backed idempotency/outbox components, and MinIO adapters once. Services receive ports, not request objects. A missing dependency fails readiness; per-router construction was rejected because it hides configuration and fragments transaction policy.

### 2. Every repository scopes tenant before resource identity

Repository methods accept tenant context and resource identifiers together and return absence for cross-tenant records. Services map absence to `resource_not_found`, preventing existence disclosure.

### 3. Object mutations use durable intent and reconciliation

The service records operation intent, quota reservation, and audit intent in a database transaction, calls MinIO, verifies the result, then settles persistence. A worker retries pending outcomes and compensates where safe. This is chosen over two-phase commit because S3 does not participate in database transactions.

### 4. MinIO is verified by capability, not brand

Development configuration explicitly enables path-style addressing and permits HTTP only in development. Readiness is non-destructive; integration tests use unique prefixes and explicitly test presigning, multipart, copy, and delete.

## Risks / Trade-offs

- [External success can outlive a database failure] → persist intent/outcome and reconcile pending operations.
- [Strict wiring may expose incomplete adapters early] → fail readiness with actionable dependency names.
- [Integration tests need a running MinIO service] → retain fake-port unit tests and make integration tests opt-in.

## Migration Plan

1. Define ports, typed results, and composition-root validation.
2. Replace placeholder stores domain by domain, adding tenant-scoped repository tests.
3. Enable object mutations only after intent, audit, quota, and reconciliation paths are present.
4. Run contract, migration, lint, type, and integration suites; rollback by disabling write capabilities while retaining recovery records.
