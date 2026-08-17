## 1. Platform permission baseline and migration

- [x] 1.1 Define the explicit platform read-permission vocabulary for accounts, tenants, roles, Support Access, and platform audit.
- [x] 1.2 Update built-in platform role definitions so `platform_admin` includes every required control-plane read permission, including `platform.tenants.read`.
- [x] 1.3 Implement idempotent add-only reconciliation for existing built-in platform roles without modifying custom roles.
- [x] 1.4 Add a versioned migration or audited maintenance command that applies the built-in-role reconciliation to existing databases.
- [x] 1.5 Add tests for new databases and already-initialized databases proving an existing platform administrator can list tenants after reconciliation.

## 2. Platform control-plane read model

- [x] 2.1 Add safe platform-account summary and paginated account-directory repository queries with identifier filtering and lifecycle filtering.
- [x] 2.2 Add platform-role and platform-role-binding summary queries with stable binding identifiers, user summaries, expiry, and revocation state.
- [x] 2.3 Add Support Access list and detail queries with derived pending, approved, revoked, and expired states.
- [x] 2.4 Add platform-audit list and detail queries with safe actor/resource summaries and cursor pagination.
- [x] 2.5 Add application services that enforce the dedicated platform read permissions for each read model.
- [x] 2.6 Ensure all platform read models omit passwords, secret digests, raw sessions, API-key secrets, object credentials, and tenant file content.

## 3. Platform HTTP contract and routes

- [x] 3.1 Add documented paginated account-directory and account-detail endpoints under `/api/v1/platform`.
- [x] 3.2 Add documented platform-role and platform-role-binding listing/detail endpoints, preserving existing grant and revoke operations.
- [x] 3.3 Add documented Support Access listing/detail endpoints, preserving request, independent approval, and revoke operations.
- [x] 3.4 Add documented platform-audit listing/detail endpoints with safe filters and opaque cursors.
- [x] 3.5 Define strict response DTOs, query validation, Chinese Swagger descriptions, and standard error envelopes for every new operation.
- [x] 3.6 Update operation-permission classification and runtime OpenAPI generation so every new operation declares its platform permission.
- [x] 3.7 Add explicit `PlatformTenantResponse` and `PlatformTenantPage` schemas to platform tenant list/detail/update operations.
- [x] 3.8 Ensure platform tenant PATCH returns the updated resource response, never the `TenantUpdate` request DTO.
- [x] 3.9 Add a paginated `GET /platform/role-bindings` operation with explicit response schemas.
- [x] 3.10 Add a paginated `GET /platform/support-access` operation with explicit response schemas and lifecycle status.
- [x] 3.11 Add a dedicated `ProbeResult` response schema for storage connection probes and remove request-schema response reuse.
- [x] 3.12 Scan all affected platform and storage operations for `unknown` responses and add contract regression tests.

## 4. Support Access lifecycle operations

- [x] 4.1 Preserve the existing two-person approval requirement while returning enough safe state for the frontend to show pending and terminal requests.
- [x] 4.2 Verify approved access creates only a time-bounded read-only support Membership and RoleBinding, without file-content or credential permissions.
- [x] 4.3 Add a dedicated scheduler service/container that runs Support Access expiry processing at least once per minute.
- [x] 4.4 Wire the scheduler configuration into deployment assets, health/logging, and operator documentation.
- [x] 4.5 Verify expiry and manual revocation invalidate bound tenant sessions, bump authorization state where required, and write platform audit events.

## 5. Contract, verification, and handoff

- [x] 5.1 Regenerate `contracts/openapi.yaml` and update API conventions, error catalog, and permission documentation where behavior changes.
- [x] 5.2 Add HTTP tests for platform-admin, operator, auditor, and unauthorized access to every new read route.
- [x] 5.3 Add end-to-end tests for account discovery, tenant creation with selected initial administrator, role binding discovery/revocation, and Support Access approval-to-tenant-selection flow.
- [x] 5.4 Add scheduler/integration tests proving expiry produces no usable tenant session after the bounded interval.
- [x] 5.5 Run Ruff, Mypy, targeted tests, OpenAPI/contract checks, and document any external infrastructure prerequisite.
- [x] 5.6 Provide frontend integration notes for platform navigation, pagination, support-access status display, explicit tenant selection, and read-only support banners.
- [x] 5.7 Regenerate frontend-facing OpenAPI types and verify platform tenant, role-binding, Support Access, and probe responses no longer resolve to `unknown`.

## 6. Post-implementation correctness closure

- [x] 6.1 Implement real bounded cursor pagination for platform tenants and platform roles, and bind every control-plane cursor to its normalized filters.
- [x] 6.2 Apply Support Access lifecycle filtering in SQL before page sizing; reject unsupported lifecycle-status filters at the HTTP boundary.
- [x] 6.3 Add safe approver summaries to Support Access detail and list DTOs, queries, OpenAPI, and generated frontend types.
- [x] 6.4 Correct every control-plane authorization dependency to expose its exact operation identifier and make contract verification reject shared-permission attribution fallbacks.
- [x] 6.5 Make account email and employee-number lookup exact while preserving bounded display-name search; reject unsupported account lifecycle filters before repository conversion.
- [x] 6.6 Add scheduler one-pass execution and use it for a real Compose health check against the configured persistence dependency.
- [x] 6.7 Add adversarial HTTP/repository tests for pagination, filter-bound cursors, invalid filters, safe approver output, operation attribution, and scheduler health; regenerate OpenAPI/frontend types and run Ruff, Mypy, tests, and contract validation.
