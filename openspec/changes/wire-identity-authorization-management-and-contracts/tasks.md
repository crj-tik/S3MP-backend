## 1. Persistence and domain ports

- [x] 1.1 Audit existing identity/authorization migrations and add only the indexes, constraints, revision/version columns or seeds needed to support tenant-safe management reads, role permission replacement, ETags and authorization invalidation.
- [x] 1.2 Define narrow repository ports and domain projections for users, memberships, groups, roles, role permissions, bindings, sessions, effective bindings and cursor pages.
- [x] 1.3 Complete SQLAlchemy identity repository operations with tenant-filtered locked reads, user/member create/read/list/update, group membership lookup, cursor pagination and contract-required source fields.
- [x] 1.4 Complete SQLAlchemy authorization repository operations to validate permissions, atomically replace role-permission rows, query active direct/group bindings, and create/revoke tenant-safe role bindings.
- [x] 1.5 Add repository integration tests for tenant isolation, role permission persistence, duplicate membership/group constraints, pagination boundaries and non-disclosing not-found behavior.

## 2. Identity and authorization application services

- [x] 2.1 Implement `IdentityManagementService` for `/me`, user/member management and group membership, including membership status history, session revocation and authorization-version invalidation.
- [x] 2.2 Implement `AuthorizationManagementService` for group, role and role-binding management, effective permission explanation and authorization simulation.
- [x] 2.3 Enforce default-deny, deny precedence, binding validity windows, canonical resource scope and delegator-subset validation in management service methods.
- [x] 2.4 Define an invalidation/outbox boundary for membership, group, role and binding mutations so stale sessions/caches cannot retain prior authority after commit.
- [x] 2.5 Add unit and service-level tests for permission enforcement, cross-tenant concealment, delegation denial, role permission replacement, version changes and `/me` projection.

## 3. HTTP boundary and runtime wiring

- [x] 3.1 Add strict Pydantic request and response DTOs for users, memberships, groups, roles, role bindings, effective permissions, simulations and pages; map service projections without leaking persistence fields.
- [x] 3.2 Add deterministic ETag generation and `If-Match` validation for management mutations where the public contract declares concurrency preconditions; remove unsupported declarations only if intentional behavior cannot be implemented.
- [x] 3.3 Add a reusable management permission dependency/mapping and enforce each endpoint's declared operation permission before service execution.
- [x] 3.4 Update identity and authorization routers to use typed dependencies, strict `response_model`s, validated query/path inputs and service-only orchestration.
- [x] 3.5 Wire identity context, identity management and authorization management services in `main.py` lifespan with database-backed adapters; define deterministic fail-closed behavior when database configuration is absent.
- [x] 3.6 Add HTTP tests proving unauthenticated requests return the standard 401 envelope, unauthorized management requests return 403, and cross-tenant targets return 404 without existence leakage.

## 4. Contract baseline and verification

- [x] 4.1 Reconcile `contracts/openapi.yaml` with the implemented management request/response DTOs, pagination, ETags, Location headers, status codes and stable errors; do not retain idealized fields that are not delivered.
- [x] 4.2 Extend the OpenAPI compatibility checker to recursively compare normalized 2xx JSON schemas after local-reference resolution, including required fields, properties, items, enums, nullability, unions and `additionalProperties`.
- [x] 4.3 Add checker fixtures/tests for schema mismatch reporting, generated-title normalization, page schemas, nested DTOs and nullable fields.
- [x] 4.4 Ensure permission catalog validation proves every protected identity/authorization operation has a registered catalog entry and an executable permission binding.

## 5. Production-readiness verification

- [x] 5.1 Add PostgreSQL lifecycle E2E coverage for `/me`, users, members, groups, roles, role bindings, effective permissions and simulations using production service wiring rather than fake app-state services.
- [x] 5.2 Add lifecycle regression tests that fail if `identity_management`, `authorization_management` or `/me` projection dependencies are absent after application startup.
- [x] 5.3 Run migration upgrade/downgrade validation, contract structural validation, schema compatibility validation, contract coverage and the complete test suite against the local Docker PostgreSQL environment.
- [x] 5.4 Review logs/audit payloads and verify no response, error or audit event discloses cross-tenant identifiers, raw session tokens, credentials or internal physical storage data.
