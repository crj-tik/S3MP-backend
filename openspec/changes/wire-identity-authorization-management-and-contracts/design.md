## Context

See `proposal.md` for motivation. `main.py` creates an identity context provider but leaves `identity_management` and `authorization_management` unset. The routers therefore rely on fake test-state injection. Existing SQLAlchemy storage is useful but incomplete: its public method shape differs from HTTP needs, roles do not persist permission membership, and persistence dictionaries are not public DTOs. The current contract checker treats untyped FastAPI `Any` responses as compatible because it does not compare success schemas.

## Goals / Non-Goals

**Goals:**

- Make every declared identity and authorization management operation execute through the normal application lifespan with PostgreSQL.
- Preserve a strict HTTP boundary: validated request models in, contract DTOs out; services own authorization, tenant resolution and transactions.
- Ensure role permissions, delegation, authorization-version invalidation, pagination and ETag behavior are durable and testable.
- Detect both route and response-schema drift before release.

**Non-Goals:**

- Adding external identity-provider login flows, browser session creation, or a new permissions product model.
- Changing the S3 ingestion lifecycle already specified by the archived security change.
- Making every existing non-management endpoint contract-strict in this change; the schema checker should be built generically, but DTO remediation is scoped to identity and authorization management endpoints.

## Decisions

### 1. Use distinct application services over a shared persistence facade

Create `IdentityManagementService` and `AuthorizationManagementService`, each taking narrow repository ports plus shared authorization/audit/version dependencies. The identity service owns users, memberships, `/me` projection and group membership. The authorization service owns groups, roles, role permissions, role bindings, explain and simulate. `main.py` constructs both with one session factory and assigns them to app state during lifespan.

This prevents routes from reaching ORM models and avoids treating `SqlAlchemyIdentityAdminStore` as an application service. It also lets the shared store be split or adapted behind ports without changing router signatures. Direct router-to-store injection is rejected because it bypasses authorization and cannot supply the contract DTOs.

### 2. Make database transactions reflect business atomicity

Role creation/update replaces `role_permission` rows within one transaction after validating each permission identifier. Membership status changes lock the membership, increment authorization version, write history, revoke active sessions and invalidate the tenant/principal authorization cache or outbox record before completion. Group and binding mutations use tenant-filtered locked reads and update authorization version for affected principals.

Service methods return domain projections, not ORM dictionaries. Repositories expose explicit queries for tenant resource lookup, role permissions, bindings, group-derived principals, sessions, and cursor ordering. This is preferred over ad hoc repository return dictionaries because fields and ownership are otherwise ambiguous.

### 3. Enforce declared management permissions through a reusable dependency

The management routers use a dependency/decorator that obtains `PrincipalContext`, resolves the operation's declared permission, and asks the authorization service for a scoped decision before a service method runs. The service repeats authorization for mutation targets and delegation rules so authorization remains correct for non-HTTP callers. Missing permission is `403 permission_denied`; a target outside the tenant is resolved only after caller authorization and returns `404 resource_not_found` without disclosure.

`x-permission` remains the contract catalog source, but code binds each endpoint to the same explicit operation name rather than dynamically parsing OpenAPI at request time. Dynamic schema parsing is rejected because startup determinism and static review are more important than avoiding a small explicit mapping.

### 4. Define public DTOs as the single serialization authority

Add Pydantic response models for User, Membership, Group, Role, RoleBinding, pages, EffectivePermissions and AuthorizationDecision. Application projections map internal IDs/relationships to those DTO fields, calculate `member_count`, materialize role permission names, convert `built_in` to contract `system`, and generate an opaque ETag from resource identity/version/update time. Internal `tenant_id`, raw foreign keys and persistence-only flags never reach the router response.

Use a shared opaque cursor codec bound to tenant, principal, authorization version, resource filter and sort key. List services return `{items, next_cursor}`. `If-Match` is parsed by routers and verified in service methods before mutations that declare it; unsupported optimistic concurrency is not left advertised in the contract.

### 5. Compare normalized successful response schemas in CI

Extend the OpenAPI checker to resolve local references and compare the baseline and runtime schema recursively for every declared 2xx JSON response. Normalize non-semantic generator details (titles, description/example ordering) but compare object properties, required fields, item schemas, enums, nullability, `additionalProperties`, `allOf`/`oneOf`, and references after resolution. Report path, method and status for each difference.

Route coverage remains a separate fast structural check. Add real PostgreSQL lifespan tests for representative list/detail/create/update/binding/explain/simulate and `/me` flows. Tests may use authenticated fixtures, but must not set `identity_management`, `authorization_management`, or `identity_context_provider` to fake implementations for production-readiness assertions.

## Risks / Trade-offs

- [Permission bootstrap deadlock] → Seed/document a tenant administrator role and test first-management-principal setup explicitly; keep bootstrap outside request-time default-allow logic.
- [Authorization-version fan-out from group/role changes] → Transactionally record affected principals and invalidate via an outbox/cache version strategy; start with correctness over bulk-update optimization.
- [DTO migration breaks current consumers] → Treat OpenAPI as the compatibility baseline, add fixture-based contract tests, and release only after frontend regeneration against the corrected schema.
- [Schema comparison produces false positives from FastAPI] → Normalize documented generator-only keys and maintain focused checker fixtures for references, pages and nullable fields.
- [Long-lived operations observe revoked grants] → Re-evaluate authorization at service boundaries and keep existing file-operation authorization-version checks.

## Migration Plan

1. Add repository ports, service implementations, strict DTOs and production dependency wiring behind the current routes.
2. Run migrations/seeds needed for role-permission integrity; deploy with existing routes unchanged.
3. Enable real-lifecycle E2E and schema comparison in CI, then update the OpenAPI baseline only where the implemented public behavior intentionally differs.
4. Roll back application code by redeploying the prior version; database additions are additive. Do not roll back permission or audit records destructively.

## Open Questions

- Initial administrator/bootstrap ownership for a new tenant is not represented by the current management routes. It should be defined by tenant provisioning before enabling self-service management, without changing the HTTP contract in this change.
