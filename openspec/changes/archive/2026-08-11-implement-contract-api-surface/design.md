## Context

The project began with a layered backend design: HTTP adapters call application services; application services coordinate domain rules and ports; persistence and S3 remain infrastructure concerns. The current API surface has routes and some domain helpers, but route registration alone does not establish service wiring, tenant-safe persistence, authorization enforcement, or reliable coordination with S3.

## Goals / Non-Goals

**Goals:**
- Restore the original application-layer boundary for every public API use case.
- Make service construction explicit in the application composition root and testable without HTTP.
- Provide safe, recoverable state transitions across database, object storage, quota, and audit systems.

**Non-Goals:**
- Treat a route forwarding to `app.state` as a completed use case.
- Let routers access ORM sessions or S3 clients directly.
- Make distributed database/S3 changes falsely atomic.
- Add backend compatibility paths or error codes for known frontend Mock defects.

## Decisions

### 1. Application services own use-case orchestration

Each service accepts `PrincipalContext` and typed commands, returns typed results, and owns authorization, tenant resolution, business invariants, idempotency, ETag checks, and audit intent. Routers only decode contract DTOs and map results to responses. Passing bare tenant IDs from routes was rejected because it loses principal state, credential provenance, scope, and authorization version.

The service map is:

| Service | Responsibility |
|---|---|
| `IdentityAdministrationService` | members, groups, roles, bindings, membership lifecycle |
| `AuthorizationQueryService` | effective permissions and simulation |
| `ApplicationLifecycleService` | applications, owners, orphan/takeover state |
| `ApiKeyLifecycleService` | issue, rotate, revoke, authenticate, scope/rate-limit checks |
| `StorageManagementService` | connections, spaces, capability probes, credential references |
| `FileQueryService` | authorized file list, metadata, and download eligibility |
| `UploadCommandService` | upload creation, direct/proxy selection, completion, quota settlement |
| `MultipartCommandService` | multipart lifecycle and expiry cleanup |
| `ObjectOperationService` | copy, move, delete, batch confirmation, recovery status |
| `QuotaAdministrationService` | quota policy, reservations, settlement, reconciliation |
| `AuditQueryService` / `AuditWriter` | immutable event write and tenant-scoped query |
| `ContractRuntimeService` | shared idempotency, ETag, cursor, and route coverage rules |

### 2. Ports and composition root are explicit

Application services depend on repository, authorization, object-storage, quota, audit, idempotency, outbox, clock, and signing ports. SQLAlchemy implementations, Redis implementations, and the S3 adapter are assembled once in the FastAPI lifespan/composition root. Missing required services fail startup/readiness rather than yielding request-time `internal_error`. Per-router service construction was rejected because it fragments transactions and makes test substitution unsafe.

### 3. Tenant-safe persistence and typed boundaries

Every repository operation receives tenant context plus resource ID and returns domain records or typed result objects. HTTP DTOs, ORM models, and domain objects are not passed across layers unchanged. Cross-tenant resources are concealed as `resource_not_found` before domain mutation.

### 4. Local MinIO is the development object-storage baseline

The concrete development `ObjectStoragePort` adapter targets the locally deployed MinIO S3-compatible service with an explicit endpoint, `us-east-1` region, path-style addressing, and the designated development bucket. The adapter uses AWS Signature Version 4 and obtains access credentials solely from `S3MP_*` environment-variable or secret-file references; no credential value is stored in source, planning artifacts, logs, audit events, or API responses.

An HTTP endpoint is permitted only when the active environment is explicitly `development`; production configuration keeps the TLS requirement and provides a distinct endpoint, bucket, and credential reference. Startup/readiness performs a non-destructive bucket and permission probe. Integration tests use an isolated, run-specific test prefix and may only clean objects under that prefix. They verify capabilities (head/list, direct/proxy upload, presigning, multipart, copy, and delete) rather than assuming compatibility merely because the service identifies as MinIO. Browser CORS remains an independently configured and verified concern.

### 5. Database and object-storage work use a recoverable saga

The database transaction first persists idempotency state, operation/upload intent, quota reservation, and redacted audit intent. The application service then invokes the object-storage port and verifies the observed object. A second transaction settles/releases quota and appends the final audit outcome. If external work succeeds but final persistence fails, the durable operation record is reconciled by an outbox/worker; responses use failed or `partial_failure`, never unverified success.

### 6. Audit is a security dependency for high-risk commands

Signature issuance, quota mutation, copy/move/delete, and credential lifecycle commands require durable redacted audit intent before success. The writer exposes an append-only port; no business API receives a mutation interface for audit events. Audit failure closes these commands with `audit_unavailable`.

### 7. Tests prove services before routes

Each vertical slice is tested at three levels: service tests with fake ports; repository/adapter integration tests; and HTTP contract tests through the application factory. Route coverage is necessary but is insufficient without service and failure-path tests.

## Risks / Trade-offs

- [The service map increases initial implementation work] → Keep each service focused on cohesive use cases and share only ports/cross-cutting policy.
- [S3 and database are not one transaction] → Persist intent/outcome and use workers for reconciliation and compensation.
- [Strict startup wiring can block partial deployments] → Use explicit capability flags for optional storage write features while requiring services for registered routes.
- [Reopening route tasks can appear to lose progress] → Preserve existing routers as adapters but require service-level verification before re-closing tasks.

## Migration Plan

1. Introduce ports, typed commands/results, and composition-root wiring alongside existing router shells.
2. Move one vertical slice at a time behind application services, keeping published paths and schemas stable.
3. Add recovery worker handling for pending external operations before enabling storage write capabilities.
4. Enable features by connection capability flags; rollback disables writes while retaining operation/audit records for recovery.
