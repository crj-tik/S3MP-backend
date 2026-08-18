## 1. API and application-layer filters

- [x] 1.1 Add `application_id` to the storage-space list route, service port, service method, and cursor query scope.
- [x] 1.2 Add `storage_space_id` to the tenant role-binding list route, service port, service method, and cursor query scope.
- [x] 1.3 Add `resource_type` and `resource_id` to the platform audit list route, control-plane port, service method, and cursor query scope.
- [x] 1.4 Preserve existing validation, permission dependencies, tenant boundaries, lifecycle filters, and response shapes for all three endpoints.

## 2. Persistence and query correctness

- [x] 2.1 Apply storage-space application filtering in SQL before pagination while retaining active tenant/application/connection/space constraints.
- [x] 2.2 Apply role-binding storage-space filtering in SQL within the current tenant boundary and preserve scope serialization.
- [x] 2.3 Apply platform audit resource filters in SQL with AND semantics alongside the existing action filter.
- [x] 2.4 Ensure every cursor/cache query key contains the normalized complete filter set and rejects cross-filter cursor reuse.
- [x] 2.5 Review existing indexes; storage application and role scope filters are covered, and no evidence currently requires a migration or new audit index.

## 3. Contract and verification

- [x] 3.1 Update `contracts/openapi.yaml` and runtime Swagger descriptions for all new query parameters and cursor semantics.
- [x] 3.2 Add route/service/repository tests for matching filters, empty results, invalid UUID/length validation, and AND composition.
- [x] 3.3 Add cross-tenant and inactive-resource isolation tests for storage spaces and role bindings.
- [x] 3.4 Add pagination tests proving filtered rows are selected before page sizing and cursors cannot cross filter sets.
- [x] 3.5 Run targeted tests, OpenAPI validation, Ruff, Mypy, and strict OpenSpec validation; record results before marking the Change complete.

## 4. Defect hardening

- [x] 4.1 Restrict storage-space role-binding filters to active tenant, application, connection, and namespace records.
- [x] 4.2 Normalize audit filter values before both SQL filtering and cursor fingerprint generation.
- [x] 4.3 Preserve legacy positional RoleBinding store arguments and rerun targeted regression checks.
