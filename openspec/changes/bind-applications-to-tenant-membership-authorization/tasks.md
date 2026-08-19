## 1. Data Model and Migration

- [ ] 1.1 Add the application-to-membership binding model/table with tenant-safe composite foreign keys, one effective binding per application, lifecycle fields, audit fields, indexes, and migration script.
- [ ] 1.2 Add repository methods to create, read, replace, revoke, and validate bindings; reject cross-tenant application/membership pairs with stable API errors.
- [ ] 1.3 Add application authorization state/summary fields and deterministic legacy migration reporting; mark ambiguous or unmapped existing applications as `authorization_unconfigured`.

## 2. Authorization Resolution

- [ ] 2.1 Implement an application authorization resolver that keeps the API-key authenticated application principal and loads its current tenant membership representative at request time.
- [ ] 2.2 Resolve the representative membership's user principal and tenant-scoped group principals without global-user or cross-tenant role lookup; reject inactive, expired, revoked, or mismatched bindings.
- [ ] 2.3 Implement effective permission intersection across API-key scopes, representative direct/group grants, storage-space/prefix scope, governance, and operation allowlist, with deny precedence and source explanations.
- [ ] 2.4 Add authorization cache keys and invalidation for application, tenant, membership authorization version, binding version, key status, and group changes; revalidate before delayed jobs execute.
- [ ] 2.5 Emit audit data that records the application actor plus representative membership/user/group source, decision, tenant, space, namespace, prefix, operation, and deny reason without secrets.

## 3. Application Management API

- [ ] 3.1 Extend application create/update contracts to accept a same-tenant membership representative and return a non-secret representative summary and authorization state.
- [ ] 3.2 Add bind, rebind, read, and revoke representative endpoints with optimistic concurrency/version checks, lifecycle validation, and idempotent behavior where appropriate.
- [ ] 3.3 Enforce management-plane boundaries: application API keys cannot change their own representative or grant roles; only authorized tenant/platform operators can manage bindings.
- [ ] 3.4 Update OpenAPI schemas, endpoint catalog, error-code catalog, audit-event catalog, and frontend integration documentation.

## 4. Data-Plane Integration

- [ ] 4.1 Integrate representative-aware authorization into upload, download, delete, list, multipart, copy, and metadata operations while preserving application namespace and canonical-key checks.
- [ ] 4.2 Ensure shared-storage space and prefix checks use the request tenant/application and resolved representative permissions; verify cross-tenant and cross-application access remains denied.
- [ ] 4.3 Apply the same representative/lifecycle revalidation to delayed tasks, retries, and queued storage operations.

## 5. Verification and Rollout

- [ ] 5.1 Add unit tests for direct roles, group roles, deny precedence, key-scope intersection, inactive/expired membership, binding replacement, and multi-tenant users.
- [ ] 5.2 Add API/integration tests for create/bind/rebind/revoke, invalid cross-tenant requests, unconfigured applications, audit explanations, and authorization error contracts.
- [ ] 5.3 Add end-to-end storage tests for allowed and denied upload/download/delete, multipart, canonical prefixes, namespace isolation, revocation, cache invalidation, and delayed-job revalidation.
- [ ] 5.4 Run migration dry-run and compatibility telemetry, remediate unconfigured applications, enable representative authorization in stages, and document legacy fallback removal.
