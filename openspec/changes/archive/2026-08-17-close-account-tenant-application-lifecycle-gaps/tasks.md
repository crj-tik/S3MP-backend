## 1. State model and migration safety

- [x] 1.1 Inventory current account, tenant, application, membership, principal, storage, credential, upload and file-operation states and map valid transitions.
- [x] 1.2 Add `deleted` state and deletion metadata columns (`deleted_at`, `deleted_by`, `deletion_reason`) to platform accounts, tenants and applications with safe defaults for existing rows.
- [x] 1.3 Add database constraints or application validation preventing invalid transitions, ordinary edits to deleted records, and restoration without required parent/Owner conditions.
- [x] 1.4 Add a pre-migration duplicate scan for normalized account email and employee number and define a deterministic remediation report.
- [x] 1.5 Replace unconditional account email and employee-number uniqueness with PostgreSQL partial unique indexes covering only `status <> 'deleted'`, including a safe down-migration plan.
- [x] 1.6 Add migration tests for existing rows, null employee numbers, deleted identity reuse and active identity conflicts.

## 2. Account lifecycle closure

- [x] 2.1 Add authorized soft-delete, status transition and permitted restore service operations for platform accounts with actor, reason and audit attribution.
- [x] 2.2 Revoke account sessions, platform role bindings and applicable tenant sessions/memberships atomically or through an idempotent durable cleanup workflow when an account is deleted.
- [x] 2.3 Ensure login, account-session resolution, account context, platform account lookup and tenant selection reject deleted accounts uniformly without existence leaks.
- [x] 2.4 Update platform account list/detail queries to apply default deleted filtering and expose only safe lifecycle metadata; add an explicit authorized historical query path.
- [x] 2.5 Add account lifecycle HTTP contract schemas, permissions, error cases and audit events.

## 3. Tenant lifecycle closure

- [x] 3.1 Add tenant soft-delete, suspended/active transitions and guarded restore operations with platform authorization and audit events.
- [x] 3.2 On tenant deletion, invalidate tenant sessions, memberships, Principal authorization, RoleBindings, API Keys, storage resources and pending tenant data-plane work.
- [x] 3.3 Make account tenant summaries, tenant selection, tenant context, platform tenant lists/details and tenant-scoped queries consistently enforce tenant status.
- [x] 3.4 Add explicit historical tenant listing/detail behavior for authorized platform audit or cleanup workflows without re-enabling access.
- [x] 3.5 Add tenant lifecycle HTTP contract schemas, operation permissions, state-transition errors and audit response coverage.

## 4. Application and credential lifecycle closure

- [x] 4.1 Add application soft-delete, guarded restore and explicit status transition service operations while preserving `pending_takeover` as a distinct governance state.
- [x] 4.2 Ensure application list/detail/update/takeover and Owner queries distinguish active, pending-takeover, suspended and deleted applications.
- [x] 4.3 On application deletion, disable the application Principal, revoke or expire API Keys, invalidate application authorization versions and cancel new application data-plane requests.
- [x] 4.4 Make API Key issuance, lookup, authentication, rotation, revocation and delayed authorization require active tenant, active application and enabled Principal state.
- [x] 4.5 Add application lifecycle HTTP contract schemas, historical-read boundaries, restore preconditions and audit coverage.

## 5. Storage and file state propagation

- [x] 5.1 Add lifecycle-aware joins and default filters for storage connections and Storage Spaces, including active tenant and active parent connection requirements.
- [x] 5.2 Require active tenant, Storage Space and applicable application/Principal state for file listing, metadata reads, uploads, multipart sessions, presigning and object operations.
- [x] 5.3 Make deletion of a tenant, application or Storage Space invalidate upload/multipart sessions and prevent queued file operations from starting.
- [x] 5.4 Extend cleanup workers to process invalidated records idempotently and retain auditable cancelled/failed outcomes without logging credentials or full URLs.
- [x] 5.5 Add integration tests for deleted-parent IDOR attempts, stale sessions, stale API Keys, storage listing and worker execution after lifecycle changes.

## 6. Query and authorization audit

- [x] 6.1 Build a repository query matrix covering every list/detail/authentication/worker read for accounts, tenants, memberships, principals, applications, API Keys, storage, files, quotas and audit records.
- [x] 6.2 Update missing parent-status joins and filters before pagination, including tenant, membership, user, principal, application, connection and Storage Space relationships.
- [x] 6.3 Verify default-deny behavior for deleted resources and uniform `404`/`403` mapping that does not reveal deleted-resource existence to unauthorized callers.
- [x] 6.4 Add explicit `include_deleted` or historical endpoints only to platform audit/cleanup scopes, with permission checks and safe response projections.
- [x] 6.5 Add cross-tenant and cross-state authorization tests for every affected resource family.

## 7. Verification and rollout

- [x] 7.1 Add state-machine, transition, restore, uniqueness, propagation and audit tests across service and persistence layers.
- [x] 7.2 Regenerate and validate OpenAPI/typed frontend contract changes for lifecycle fields, operations, query parameters and error envelopes.
- [x] 7.3 Run migrations against a copy of the current development database and verify duplicate scan, index creation, rollback and idempotent cleanup behavior.
- [x] 7.4 Run focused identity, platform, application, storage and file tests, then the relevant full test subset with isolated pytest temp directories.
- [x] 7.5 Document deployment order, worker restart requirements, cleanup observability and rollback/restore runbook.
