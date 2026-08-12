## Context

See proposal.md for motivation. The application currently has declared routes and partial adapters, but runtime composition leaves some services unreachable or backed by no-op stores. The existing test change also demonstrated that direct infrastructure tests are not self-describing when dependencies are unavailable. This design keeps HTTP routers thin and makes application services the sole coordinator of identity, persistence, object storage, quota, audit, and asynchronous recovery.

## Goals / Non-Goals

**Goals:**

- Make the `/api/v1` contract, authenticated request path, and application persistence executable end to end.
- Make every enabled file mutation use verified object storage and durable, recoverable operation state.
- Make Redis-backed rate limiting and event delivery safe under contention and recoverable after consumer failure.
- Make local runtime and integration testing reproducible without embedding credentials in tracked configuration.
- Establish a single quality-gate command set whose success is meaningful.

**Non-Goals:**

- Redesign the product authorization model, introduce a new cloud provider, or provide exactly-once external side effects.
- Guarantee revocation of already-issued S3 URLs before their expiry.
- Turn the local Compose profile into production orchestration.
- Rewrite every existing module solely for style; quality fixes are limited to code reached by the gate and this change's touched paths.

## Decisions

### 1. Preserve `/api/v1` as the public API base and generate the contract from the runtime shape

`/api/v1` is already the runtime router prefix and the main specifications name it as public. The OpenAPI baseline will be updated to that exact path shape, and the check will compare method, path, response status, and registered public error codes in both directions. The one-time-secret endpoint will use the catalogued `secret_not_retrievable` code.

**Alternative considered:** removing the runtime prefix to match the existing YAML. Rejected because it would break the documented versioned public API and force a wider client migration.

### 2. Authenticate once at the HTTP boundary; authorize and coordinate in application services

An authentication middleware/dependency resolves credentials into a verified `PrincipalContext` and rejects missing or invalid credentials before router dispatch. App assembly injects real service implementations whenever their enabled dependencies are configured; no-op stores remain test-only fixtures and cannot silently back protected production routes. Routers parse/serialize HTTP only, while application services receive the context and enforce tenant scoping, permissions, idempotency, quota, audit, and external-operation ordering.

**Alternative considered:** letting each router build or infer identity context. Rejected because it duplicates security decisions and causes inconsistent tenant boundaries.

### 3. Establish database intent before S3 work and persist verified terminal state afterwards

Upload and object-operation services will create an operation record and reserve quota in one database transaction before object storage is called. Completion uses object metadata verification before marking a file available and settling quota. Copy/move/delete record target/source identities, verification results, and terminal outcome. If a move copy succeeds but source deletion fails, the operation is persisted as `partial_failure` with retry/recovery metadata.

Database transactions do not span MinIO. The durable operation record is therefore the recovery boundary; a reconciler/worker retries incomplete work safely using operation state and idempotency keys.

**Alternative considered:** write the database only after S3 returns. Rejected because a process crash would leave untracked objects and an ambiguous client result.

### 4. Implement the full MinIO-compatible port at the adapter boundary

The object-storage adapter will expose the concrete operations required by file services: put/head/delete, presigned PUT/GET, multipart create/upload-part/list-parts/complete/abort, and copy. It will use the configured bucket, endpoint, region, and path-style setting, and return normalized metadata rather than provider-specific structures. Services use the port only; they do not construct MinIO client calls or placeholder URLs.

**Alternative considered:** retain DB-only file sessions and expose mock download URLs. Rejected because it violates the file lifecycle contract and conceals failed storage operations.

### 5. Use durable Redis Streams consumer groups for outbox delivery and server-side atomicity for rate limiting

Outbox events have a stable UUID, payload, attempt count, and timestamps. Producers append to a Redis Stream. Consumers read through a named consumer group and acknowledge only after successful handling; pending messages are claimed after a lease timeout, retried with bounded attempts, then moved to a dead-letter stream with failure details. A Lua script performs rate-limit prune, count, admission, and expiry in one server-side operation.

**Alternative considered:** repair the existing list plus lease-key scheme. Rejected because `LPOP` before lease acquisition and `nack` behavior make loss recovery fragile; Streams provide pending-entry and claim semantics explicitly.

### 6. Separate local runtime and test profiles, with a destructive-test guard

Compose provides a local `dev` profile containing API, PostgreSQL, Redis, MinIO, bucket initialization, and a migration job. Secret file references or untracked environment files supply credentials. Integration tests require explicit `S3MP_TEST_*` settings and a test-database marker/name guard before migration resets or destructive setup. A preflight command reports unavailable PostgreSQL, Redis, or MinIO clearly before the suite runs.

**Alternative considered:** reuse implicit localhost defaults and the development database. Rejected because it is non-reproducible and makes migration tests unsafe.

### 7. Gate in layers, then run the integrated acceptance suite

The implementation order is: deterministic persistence/contract fixes, authenticated app composition, MinIO lifecycle services, Redis reliability, Compose/test preflight, then static and full integration gates. Each defect receives a regression test that fails before the implementation and passes afterwards. Integration tests are separate from fast unit tests but use an explicit documented command in the full gate.

## Risks / Trade-offs

- [Non-transactional database/S3 boundary] → Persist intent before external calls, verify after calls, and retain retryable terminal/partial states.
- [Redis Streams introduce operational state] → Bound retention, configure consumer groups, document pending-message recovery, and expose stream health in readiness/metrics.
- [Authentication middleware can change existing test assumptions] → Preserve an explicit test-only context injection mechanism and add HTTP regression tests for missing/valid context.
- [OpenAPI prefix correction can require frontend regeneration] → Treat `/api/v1` as the contract change point, regenerate clients, and retain contract verification in CI.
- [Integration migrations are destructive] → Require an explicit test database identity guard and refuse unsafe targets before migration reset.
- [Full quality gate may reveal unrelated debt] → Fix errors in touched/runtime paths first, then record remaining independent debt separately rather than masking it.

## Migration Plan

1. Add regression tests and contract deltas for the currently observed defects.
2. Ship database/application fixes and authentication composition behind the existing API prefix; no public path removal occurs.
3. Add any required operation/outbox schema migration, deploy it before enabling the corresponding worker path, and retain compatibility readers for existing operation rows.
4. Update the OpenAPI baseline and regenerate dependent clients before releasing the corrected error code/path contract.
5. Bring up the integrated profile, run migrations, preflight dependencies, and execute the full gate against isolated test infrastructure.
6. Roll back by disabling the worker and using existing operation records for reconciliation; database schema changes must remain backward-compatible for at least one deployment rollback window.
