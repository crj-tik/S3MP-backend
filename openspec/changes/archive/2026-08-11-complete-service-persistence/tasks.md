## 1. Shared service and persistence foundation

- [x] 1.1 Define typed commands/results and ports for repositories, authorization, idempotency, quota, audit, object storage, clock, and outbox.
- [x] 1.2 Complete composition-root wiring with concrete service dependencies and fail readiness for any placeholder or missing registered service.
- [x] 1.3 Implement shared idempotency, ETag, cursor, canonical-key, and stable-error enforcement at the service boundary.
- [x] 1.4 Add application factory and fake-port tests for service wiring and mutation policies.

## 2. Identity, authorization, applications, and API Keys

- [x] 2.1 Implement tenant-scoped SQLAlchemy repositories for memberships, groups, roles, bindings, authorization-version changes, and session invalidation.
- [x] 2.2 Implement IdentityAdministrationService and AuthorizationQueryService, including concealed cross-tenant lookup and explain/simulation results.
- [x] 2.3 Adapt identity and authorization routers to typed services and add repository/service/HTTP coverage.
- [x] 2.4 Complete application, owner, and API Key repositories with ETags, lifecycle state, one-time-secret handling, redacted audit intents, and rate-limit ports.
- [x] 2.5 Complete ApplicationLifecycleService and ApiKeyLifecycleService, then adapt their routers and add tenant-isolation and secret-redaction tests.

## 3. Storage and file query lifecycle

- [x] 3.1 Complete storage connection and space repositories, validate development MinIO configuration, and expose non-destructive capability probes.
- [x] 3.2 Implement file-object repository and FileQueryService for canonical-key scoped listing, metadata, download eligibility, and delete eligibility.
- [x] 3.3 Adapt storage and file-query routers to typed services, ETag/idempotency policy, and contract DTOs.
- [x] 3.4 Add MinIO adapter tests plus opt-in isolated-prefix integration tests for readiness, presigning, and cleanup safety.

## 4. Upload, multipart, and object-operation orchestration

- [x] 4.1 Implement quota reservation persistence and UploadCommandService intent, direct/proxy selection, verification, settlement, and audit outcomes.
- [x] 4.2 Implement MultipartCommandService session/part persistence, principal binding, provider completion verification, abort, expiry cleanup, and quota release.
- [x] 4.3 Implement ObjectOperationService copy, move, delete, batch confirmation, observed-state verification, and partial-failure persistence.
- [x] 4.4 Implement outbox/reconciliation worker retries, compensation, and recovery status queries.
- [x] 4.5 Adapt upload, multipart, and object-operation routers to command services without direct storage access.
- [x] 4.6 Add fake-S3, repository, worker, MinIO integration, and HTTP tests for retry, expiry, oversized object, partial failure, and URL redaction paths.

## 5. Quota, audit, and contract verification

- [x] 5.1 Implement QuotaAdministrationService/repositories for policy update, reservation, settlement, release, and reconciliation.
- [x] 5.2 Implement append-only AuditWriter and AuditQueryService with tenant filters, immutable persistence, and centralized redaction.
- [x] 5.3 Enforce audit-before-success and failure closure for high-risk commands.
- [x] 5.4 Adapt quota and audit routers to service-level permissions, ETags, cursors, and contract responses.
- [x] 5.5 Verify runtime route-to-service coverage and all declared method, path, header, status, error, pagination, ETag, and idempotency semantics.
- [x] 5.6 Run migrations, OpenAPI baseline, ruff, mypy, unit, HTTP, and opt-in MinIO integration suites; document any frontend contract corrections.