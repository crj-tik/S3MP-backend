## 1. Data Model and Migration

- [x] 1.1 Add the application-to-membership binding model/table with tenant-safe composite foreign keys, one effective binding per application, lifecycle fields, audit fields, indexes, and migration script.
- [x] 1.2 Add repository methods to create, read, replace, revoke, and validate bindings; reject cross-tenant application/membership pairs with stable API errors.
- [x] 1.3 Add application authorization state/summary fields and deterministic legacy migration reporting; mark ambiguous or unmapped existing applications as `authorization_unconfigured`.

## 2. Authorization Resolution

- [x] 2.1 Implement an application authorization resolver that keeps the API-key authenticated application principal and loads its current tenant membership representative at request time.
- [x] 2.2 Resolve the representative membership's user principal and tenant-scoped group principals without global-user or cross-tenant role lookup; reject inactive, expired, revoked, or mismatched bindings.
- [x] 2.3 Implement effective permission intersection across API-key scopes, representative direct/group grants, storage-space/prefix scope, governance, and operation allowlist, with deny precedence and source explanations.
- [x] 2.4 Add authorization cache keys and invalidation for application, tenant, membership authorization version, binding version, key status, and group changes; revalidate before delayed jobs execute.
- [x] 2.5 Emit audit data that records the application actor plus representative membership/user/group source, decision, tenant, space, namespace, prefix, operation, and deny reason without secrets.

## 3. Application Management API

- [x] 3.1 Extend application create/update contracts to accept a same-tenant membership representative and return a non-secret representative summary and authorization state.
- [x] 3.2 Add bind, rebind, read, and revoke representative endpoints with lifecycle validation and idempotent replacement behavior.
- [x] 3.3 Enforce management-plane boundaries: application API keys cannot change their own representative or grant roles; only authorized tenant/platform operators can manage bindings.
- [x] 3.4 Update runtime OpenAPI surface and add frontend integration documentation for representative binding, lifecycle, and authorization semantics.

## 4. Data-Plane Integration

- [x] 4.1 Integrate representative-aware authorization into upload, download, delete, list, multipart, copy, and metadata operations while preserving application namespace and canonical-key checks.
- [x] 4.2 Ensure shared-storage space and prefix checks use the request tenant/application and resolved representative permissions; verify cross-tenant and cross-application access remains denied.
- [x] 4.3 Apply representative/lifecycle revalidation to delayed tasks and queued storage operations.

## 5. Verification and Rollout

- [x] 5.1 Run the existing unit/regression suites covering direct roles, group roles, deny precedence, key-scope intersection, membership lifecycle, and multi-tenant isolation.
- [x] 5.2 Run the application HTTP/repository and authorization HTTP/integration suites covering lifecycle and authorization error contracts.
- [x] 5.3 Run the file repository, file HTTP, worker, canonical-prefix, namespace, revocation, and delayed-operation regression suites.
- [x] 5.4 Run migration dry-run and compatibility checks; document that production rollout still requires applying the generated migration SQL and remediating `authorization_unconfigured` applications.
