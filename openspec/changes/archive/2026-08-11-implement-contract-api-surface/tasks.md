## 1. Application-layer foundation

- [ ] 1.1 Define typed commands/results and application-service interfaces that accept PrincipalContext for all public use cases.
- [ ] 1.2 Define tenant-scoped repository, authorization, object-storage, quota, audit, idempotency, clock, and outbox ports.
- [ ] 1.3 Implement composition-root service wiring in the application lifespan and fail readiness when a registered route lacks its required service.
- [ ] 1.4 Implement shared application-service idempotency, ETag, cursor, and stable-error policies.
- [ ] 1.5 Add service-level fake-port tests and startup wiring tests for the shared foundation.

## 2. Identity and authorization services

- [ ] 2.1 Implement IdentityAdministrationService for member detail, group membership, role binding, lifecycle, and authorization-version updates.
- [ ] 2.2 Implement AuthorizationQueryService for effective permissions and simulations with concealed cross-tenant lookup.
- [ ] 2.3 Adapt identity and authorization routers to typed commands/results only.
- [ ] 2.4 Add service, repository, and HTTP tests for inactive membership, IDOR, cursor invalidation, stale writes, and explainability.

## 3. Application and API Key services

- [ ] 3.1 Implement SQLAlchemy repositories and typed records for applications, owners, and API Keys with tenant filters and ETags.
- [ ] 3.2 Implement ApplicationLifecycleService for create/update/owner/orphan/takeover workflows and audit intent.
- [ ] 3.3 Implement ApiKeyLifecycleService for issue, one-time secret, rotate, revoke, authenticate, scope intersection, and rate limiting.
- [ ] 3.4 Adapt application/API Key routers to these services and exact contract DTOs.
- [ ] 3.5 Add service, repository, and HTTP tests for secret non-retrieval, revoked keys, cross-tenant IDs, idempotency, and audit redaction.

## 4. Storage and file query services

- [ ] 4.1 Implement storage connection/space repositories and StorageManagementService with redacted credential references, development MinIO configuration validation, and non-destructive capability probes.
- [ ] 4.2 Implement FileQueryService and file-object repository for authorized list, metadata, delete eligibility, and download eligibility.
- [ ] 4.3 Adapt storage/file query routers to typed service commands/results and tenant authorization.
- [ ] 4.4 Add service, adapter, and HTTP tests for canonical keys, prefix scope, capability errors, tenant concealment, and response mapping.
- [ ] 4.5 Implement the MinIO-backed object-storage adapter with explicit development-only HTTP/path-style handling, secret references, and readiness probing.
- [ ] 4.6 Add isolated-prefix MinIO integration tests for signed upload/download, multipart, copy/delete, cleanup safety, and capability reporting.

## 5. Upload, multipart, and object-operation commands

- [ ] 5.1 Implement UploadCommandService with upload-session persistence, direct/proxy selection, quota reservation, completion verification, and audit intent/outcome.
- [ ] 5.2 Implement MultipartCommandService with session/part persistence, principal binding, completion verification, abort, expiry cleanup, and quota release.
- [ ] 5.3 Implement ObjectOperationService for copy/move/delete/batch confirmation, external verification, and partial-failure recovery.
- [ ] 5.4 Implement object-storage and outbox/worker adapters for verification, retry, reconciliation, and compensation.
- [ ] 5.5 Adapt upload, multipart, and file-operation routers to command services without direct storage access.
- [ ] 5.6 Add service, fake-S3, repository, worker, and HTTP tests for retries, expiry, oversized objects, partial failures, and URL redaction.

## 6. Quota and audit services

- [ ] 6.1 Implement QuotaAdministrationService and repositories for policy updates, reservations, settlement, release, and reconciliation.
- [ ] 6.2 Implement append-only AuditWriter and AuditQueryService with tenant-scoped filtering and redaction enforcement.
- [ ] 6.3 Enforce audit-before-success for high-risk commands and audit failure closure.
- [ ] 6.4 Adapt quota/audit routers to service-level ETag, permission, pagination, and typed response policies.
- [ ] 6.5 Add quota/audit service, repository, and HTTP tests including immutable events and audit failure closure.

## 7. End-to-end contract verification

- [ ] 7.1 Verify every OpenAPI operation has one registered router backed by a configured application service.
- [ ] 7.2 Verify declared method, path, headers, status, errors, pagination, ETag, and idempotency behavior through HTTP tests.
- [ ] 7.3 Execute tenant-isolation, authorization-revocation, S3 capability, failure-recovery, and sensitive-data redaction scenarios.
- [ ] 7.4 Run OpenAPI baseline, migration, ruff, mypy, and full test suites; document frontend Mock path/error-code corrections.
