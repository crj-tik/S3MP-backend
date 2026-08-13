## 1. Baseline inventory and schema preparation

- [x] 1.1 Add a read-only security audit command that inventories storage-space namespace overlap, unscoped provider targets, unsafe durable work, orphan applications, and delegation violations without outputting secrets or object content.
- [x] 1.2 Add additive migrations and ORM fields for provider-target versioning, immutable tenant/storage-space namespace metadata, durable human membership identity, and `pending_takeover` application state with necessary tenant-scoped indexes and constraints.
- [x] 1.3 Add repository projections and migration manifests that distinguish internal provider targets from public API DTOs.
- [x] 1.4 Add migration fixtures for legacy files, uploads, multipart sessions, ingestion records, pending operations, overlapping roots, and conflicting tenants.

## 2. Provider namespace isolation and safe migration

- [x] 2.1 Define a typed server-owned provider target and canonical storage-space configuration validation; reject traversal, ambiguity, and operator prefixes that cannot remain beneath the immutable namespace.
- [x] 2.2 Refactor MinIO/ObjectStorage ports and adapters so every head, put, copy, delete, multipart, and presign call uses the authorized command's bucket and derived key.
- [x] 2.3 Refactor authorized file commands, file persistence, ingestion, deletion reconciliation, and operation workers to use provider target versioning and the same derived target for authorization, persistence, and provider execution.
- [x] 2.4 Implement migration dry-run, verified copy/head/update manifests, quarantine handling, resumable cleanup, and rollback-safe legacy read support; prohibit legacy provider mutations.
- [x] 2.5 Add PostgreSQL/MinIO integration tests proving identical relative keys in different tenants/spaces cannot collide, overwrite, read, copy, delete, or receive each other's presigned URL.

## 3. Contract-driven management authorization

- [x] 3.1 Build a complete operationId-to-permission classification from OpenAPI, including storage connections/spaces, quotas, audit, identity, authorization, applications, API Keys, and access reviews.
- [x] 3.2 Replace the API-Key path-prefix blacklist with classification-driven management-route rejection that preserves API-Key access to file data-plane routes beneath `/storage_spaces`.
- [x] 3.3 Bind storage and governance routers to the shared authorization dependency and pass PrincipalContext to their services.
- [x] 3.4 Add service-layer authorization checks for storage, quota, and audit use cases so internal callers cannot bypass route enforcement.
- [x] 3.5 Extend contract verification and CI tests to fail when a declared non-public `x-permission` lacks classification or runtime enforcement.
- [x] 3.6 Add HTTP tests for human allowed/denied access and API-Key denial across every management category, including no-service-call assertions on denial.

## 4. Delegation and role-mutation hardening

- [x] 4.1 Expose permission `delegable` metadata to the authorization-management policy and enforce it for role creation, role updates, and role-binding creation.
- [x] 4.2 Enforce no-self-grant, canonical scope containment, future-but-bounded expiry, and redacted escalation audit events for role-binding mutations.
- [x] 4.3 Make built-in roles immutable and validate role permission additions against every active binding scope and the caller's delegable effective authority before persisting changes.
- [x] 4.4 Revalidate/bump all affected principals atomically after permitted role or binding changes, and cancel or invalidate stale durable work through the shared validator.
- [x] 4.5 Add adversarial authorization tests for bound-role escalation, non-delegable permissions, self-grants, expiry extension, built-in role edits, group-derived bindings, and deny precedence.

## 5. Revocation-safe delayed work and operation visibility

- [x] 5.1 Persist membership identity and authorization version for new human-created ingestion intents, delete intents, and file operations; reject or quarantine legacy records missing sufficient subject identity.
- [x] 5.2 Implement a shared delayed-subject validator that checks active/non-expired membership, current version, principal state, API-Key/application state, current scope, and current resource authorization.
- [x] 5.3 Apply the validator before ingestion reconciliation, deletion reconciliation, and every file-operation worker provider mutation; persist a redacted cancelled/failed outcome on revocation.
- [x] 5.4 Enforce creator-or-currently-delegated access for file-operation results, evaluate all affected paths for non-creators, and map internal records to contract-safe public response DTOs.
- [x] 5.5 Replace lexical file-list prefix filtering with escaped canonical directory-boundary filtering and align repository prefix representation with authorized commands.
- [ ] 5.6 Add HTTP and real-database tests for same-tenant operation IDOR, internal-field redaction, suspended membership before queued work, authorization-version change before reconciliation, and `team` versus `team2` listing isolation.

## 6. Application Owner lifecycle containment

- [x] 6.1 Add repository queries that determine whether every direct Owner is currently active in the tenant, rather than treating owner-row existence as activity.
- [x] 6.2 Trigger active-Owner recomputation after membership lifecycle mutations and through a governance scan for pre-existing drift.
- [x] 6.3 Atomically transition ownerless applications to `pending_takeover`, advance application authorization version, reject API-Key authentication, and emit redacted audit/outbox notifications.
- [x] 6.4 Implement the authorized takeover/reactivation path required to restore a pending application without exposing API Key secrets.
- [x] 6.5 Add tests for last Owner suspension/removal/expiry, stale Owner rows, API-Key rejection while pending takeover, authorized recovery, and idempotent repeated lifecycle events.

## 7. End-to-end verification and rollout evidence

- [ ] 7.1 Run format, type, unit, contract, and adversarial HTTP tests; add focused PostgreSQL/Redis/MinIO integration coverage for the modified boundaries.
- [x] 7.2 Execute migration audit and dry-run against the local infrastructure, record only aggregate counts and redacted conflict identifiers, and remediate/quarantine every unsafe record before enabling strict mode.
- [x] 7.3 Verify `/health/ready`, worker reconciliation, and contract validation under the configured local PostgreSQL, Redis, and MinIO services.
- [x] 7.4 Document rollout gates, verified rollback limitations, breaking provider-key migration behavior, and operational commands in the deployment guide.
