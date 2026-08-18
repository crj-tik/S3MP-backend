## 1. Application principal migration and API-Key authentication

- [x] 1.1 Inventory the principal, application, owner, API-Key and permission schema; define the additive migration and invariant query for one distinct application principal per application.
- [x] 1.2 Implement and test the PostgreSQL migration/backfill, including audit/report output and quarantine of legacy rows that cannot be safely attributed.
- [x] 1.3 Make application creation atomically create its application principal, application record and initial owner; update repository projections and tests.
- [x] 1.4 Replace API-Key lookup with tenant-safe Key/application/principal resolution that rejects inactive, expired, revoked or disabled components and returns the real application principal.
- [x] 1.5 Extend the authenticated access context with application ID, API-Key ID, scopes and authorization version without exposing credential material.
- [x] 1.6 Add real-database tests for successful application-Key authentication, disabled application/principal rejection, revoked/expired Key rejection and legacy migration invariants.

## 2. Management authorization and effective machine scopes

- [x] 2.1 Define the explicit existing permission-catalog mapping for application, ownership and API-Key lifecycle operations, and document any new catalog entries required by the mapping.
- [x] 2.2 Classify management and machine-resource routes; reject API-Key credentials on management routes before handler execution.
- [x] 2.3 Enforce the lifecycle permission/Owner rule in application and API-Key service methods for every target lookup and mutation.
- [x] 2.4 Implement a shared effective-permission adapter that intersects endpoint permission, API-Key scopes, RoleBinding decision and canonical storage scope with deny precedence.
- [x] 2.5 Add redacted audit events and tests for issue, rotate, revoke, cross-owner denial, API-Key management-route denial and scope-versus-prefix denial.

## 3. Authorization version and pagination correctness

- [x] 3.1 Add an application-principal authorization-version strategy and atomically advance it for application state, Key lifecycle and relevant binding changes.
- [x] 3.2 Persist sufficient authorization identity/version in file-operation and ingestion intent for later revalidation.
- [x] 3.3 Correct all identity/authorization list repositories to encode the last returned row rather than the look-ahead row as the next cursor.
- [x] 3.4 Extend the opaque cursor codec and list services to bind tenant, requester, authorization version, normalized filters and ordering.
- [x] 3.5 Add regression tests for multi-page lists, `limit=1`, filtered binding lists, tampered/cross-filter cursors and authorization-version changes.

## 4. Durable file-operation worker

- [x] 4.1 Add additive operation schema fields and migrations for canonical operation semantics, authorization evidence, attempts, lease, retry schedule, terminal error and complete state history.
- [x] 4.2 Make copy, move and delete enqueue idempotent operation intent with all source/target permissions recorded, rather than only a generic pending row.
- [x] 4.3 Implement PostgreSQL `SKIP LOCKED` claiming, leases, heartbeat/expiry recovery and state transitions for pending, running, retry_wait, succeeded, failed, partial_failure and cancelled.
- [x] 4.4 Implement idempotent MinIO copy/move/delete execution and verification, including correct partial_failure behavior after target success and source-delete failure.
- [x] 4.5 Add a separate worker entry point with periodic PostgreSQL polling and Redis wake-up hints; expose worker/reconciliation backlog and degraded wake-up readiness telemetry.
- [x] 4.6 Add concurrency, crash-after-provider-success, retry-exhaustion, idempotency and move partial-failure integration tests against PostgreSQL and MinIO.

## 5. Delayed authorization and ingestion/deletion reconciliation

- [x] 5.1 Implement a persisted-command authorization revalidator that checks current human/application/API-Key state, authorization version, scopes and canonical resource permissions without caller-controlled input.
- [x] 5.2 Invoke revalidation before every file-operation object side effect and convert revocation/state failures into redacted, auditable cancelled or failed terminal states.
- [x] 5.3 Invoke revalidation before ingestion `commit_verified_file`; quarantine or schedule controlled cleanup when a previously accepted upload is no longer authorized.
- [x] 5.4 Move ingestion and deletion reconciliation into the worker schedule with bounded retries, explicit terminal records and safe recovery of lease-expired work.
- [x] 5.5 Add PostgreSQL/Redis/MinIO integration tests for grant revocation after enqueue, Key/application disable before recovery, database-failure reconciliation and Redis-unavailable polling fallback.

## 6. Contract, rollout and operational verification

- [x] 6.1 Update OpenAPI security metadata, error responses and operation descriptions for the API-Key management restriction and file-operation terminal-state semantics; run the contract checker.
- [x] 6.2 Add pre-enforcement migration reports and deployment guards that block strict mode until application-principal and API-Key invariants pass.
- [x] 6.3 Provide deployment configuration for the worker, retry/retention limits and alerts for stale leases, terminal failures, cancellation rate and reconciliation backlog.
- [x] 6.4 Run the full unit, real PostgreSQL/Redis/MinIO acceptance and OpenSpec strict-validation suites; record any operator migration actions before enabling workers.
