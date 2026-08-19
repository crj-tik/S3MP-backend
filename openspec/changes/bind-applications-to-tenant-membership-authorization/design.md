# Design: Application Authorization Representative

## Context

An application has its own principal and API keys, while `Membership` is the tenant-scoped relationship between a user and a tenant. A `RoleBinding` may target users, groups, or applications, but current file authorization expands group bindings only for human subjects; an application therefore does not inherit the roles of the member who operates it. Storage namespaces are already derived from the tenant and application, so the missing link is authorization delegation, not S3 identity.

## Goals / Non-Goals

### Goals

- Bind each application to at most one active `Membership` in the same tenant.
- Resolve that binding at authorization time while retaining the application principal as the authenticated and audited actor.
- Include the representative user's direct roles and tenant-scoped group roles in the application's effective data-plane permissions.
- Enforce tenant, application, storage-space, prefix, key-scope, lifecycle, and deny rules on every protected request.
- Make revocation, replacement, explanation, migration, and frontend display observable and testable.

### Non-Goals

- Do not merge `Tenant`, global `User`, and tenant `Membership` into one entity.
- Do not make an application authenticate as, or impersonate, a user.
- Do not resolve a user's roles from another tenant or make a group an authenticating subject.
- Do not change S3 credentials, bucket layout, or the application namespace algorithm.
- Do not grant management-plane permissions merely because an application has a representative.

## Decisions

### 1. Store an explicit tenant-scoped representative binding

Add an `application_membership_binding` table containing `tenant_id`, `application_id`, `membership_id`, creator/audit fields, and lifecycle fields. Enforce one effective binding per application and composite foreign keys that keep both the application and membership in the same tenant. The binding references `membership_id`, rather than a global `user_id`, so tenant context cannot be lost. Rebinding is an explicit operation and is audited.

Alternatives rejected: inferring the representative from the Owner (owner lifecycle and data authorization are different concerns), or storing only a global user id (would permit cross-tenant role lookup).

### 2. Keep Owner and representative semantics separate

Application creation and an explicit bind/rebind endpoint accept a tenant membership id. Owner remains responsible for application lifecycle and takeover; it is not an implicit file permission source. New applications without a valid representative are rejected or remain `authorization_unconfigured` and cannot perform data-plane operations. Existing applications are migrated only when the mapping is deterministic; otherwise they are marked unconfigured for explicit administrator action.

### 3. Resolve permissions without changing the authenticated principal

The API-key middleware continues to authenticate `application_id`/application principal and preserves it in the request context. A resolver then loads the current representative binding, verifies tenant and membership status/version, obtains the member's user principal and groups, and returns an authorization subject containing both identities. Authorization queries use the tenant id from the application/request, never a global user lookup. Audit records identify the application as actor and include the representative membership/user/group as the delegated source.

### 4. Use an explicit intersection with deny precedence

For application data-plane requests, effective permission is the intersection of API-key scopes, representative user/group role grants, storage-space and canonical-prefix scope, governance constraints, and the operation allowlist. Any applicable deny wins. Direct and group bindings are evaluated with the existing role-binding semantics; a group is only a permission source for the resolved representative, never a bearer identity.

### 5. Revalidate lifecycle and invalidate caches

Every protected request (or a bounded, version-checked authorization cache lookup) revalidates application status, tenant status, representative membership status/expiry, membership authorization version, and key status/scope. Membership suspension, removal, representative revocation, tenant suspension, or application disablement must invalidate the binding cache and make subsequent requests fail with stable authorization errors. Delayed jobs revalidate the same state before executing.

### 6. Expose management and explanation contracts

Add create/update validation and bind, rebind, revoke, and read endpoints under the application management API. Responses expose representative membership id and a non-secret summary (user, status, version, bound time). Effective-permission/explanation responses identify the application, tenant, representative membership, user, groups, scopes, namespace/space/prefix, and deny reason. Binding and lifecycle changes emit audit events; no API secret is returned or logged.

## Risks / Trade-offs

- **Permission drift when a member's roles change** → versioned membership checks, cache invalidation, effective-permission explanation, and access-review tooling.
- **A member suspension breaks an otherwise healthy application** → surface binding health/readiness and provide explicit rebind, rather than silently falling back to Owner or legacy grants.
- **Migration can lock out existing applications** → staged rollout, deterministic-only backfill, an `authorization_unconfigured` diagnostic, and an operator migration report.
- **Group expansion adds authorization latency** → reuse tenant-scoped group queries, bound the cache, and include membership/group authorization versions in cache keys.
- **Legacy direct application RoleBindings may conflict with the new model** → define a deprecation window and telemetry, then require a representative for new/updated applications before removing legacy fallback.

## Migration Plan

1. Add the table, tenant-safe foreign keys, unique-effective-binding constraint, indexes, lifecycle columns, and audit event types.
2. Add model/repository/resolver support and API schemas for representative binding and application authorization status.
3. Deploy read-only resolution and telemetry; produce a report of applications with deterministic and ambiguous legacy ownership/role state.
4. Backfill only deterministic mappings; mark the rest `authorization_unconfigured`. During the compatibility window, retain explicitly identified legacy application grants behind a feature flag and emit warnings.
5. Enable representative-based authorization for new and updated applications, then all applications after remediation. Verify upload/download/delete, multipart, delayed jobs, revocation, and cross-tenant tests.
6. Remove the legacy fallback after the announced deprecation window and update OpenAPI, frontend contracts, runbooks, and access-review documentation.

## Open Questions

None blocking. The implementation task should choose the concrete endpoint paths and error-code names consistently with the existing application API router and API error catalog.
