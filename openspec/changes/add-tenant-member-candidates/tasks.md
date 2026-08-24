## 1. Extend candidate-query contracts

- [x] 1.1 Add the candidate response/page DTOs, route permission classification, and OpenAPI operation for `GET /api/v1/member-candidates`.
- [x] 1.2 Add the identity-management store/service port for bounded candidate lookup with normalized query and cursor inputs.

## 2. Implement tenant-scoped lookup

- [x] 2.1 Query active global users with case-insensitive fuzzy matching over email, display name, and employee number, treating blank query as no filter.
- [x] 2.2 Exclude users with any Membership row in the current tenant, preserve tenant isolation, order deterministically, and issue filter-bound opaque cursors.
- [x] 2.3 Return only candidate `id`, `email`, and `display_name` fields through the authorized route.

## 3. Verify and publish

- [x] 3.1 Add HTTP tests for permission enforcement, empty/query searches, all membership statuses exclusion, and response shape.
- [x] 3.2 Add repository/service tests for email/name/employee-number matching, cross-tenant inclusion, and cursor/query stability.
- [x] 3.3 Update contract/error documentation and run OpenAPI, lint, type, and focused test checks.
