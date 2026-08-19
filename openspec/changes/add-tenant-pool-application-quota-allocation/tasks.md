## 1. Domain model and migration

- [x] 1.1 Extend quota state with explicit allocation mode and lifecycle status, preserving tenant-total and application-reserved uniqueness.
- [x] 1.2 Add the shared Bucket allocatable capacity configuration, validation, startup diagnostics, and environment documentation.
- [x] 1.3 Add database constraints and indexes for active tenant totals, active application allocations, reservation lookups, and lifecycle-filtered queries.
- [x] 1.4 Audit existing quota rows and implement a migration/report for legacy storage-space quotas; do not delete rows with usage or active reservations.
- [x] 1.5 Add migration tests for duplicate tenant totals, duplicate application allocations, invalid states, and legacy isolation.

## 2. Allocation calculation and governance service

- [x] 2.1 Implement a single allocation calculator for tenant limit, active application allocation total, shared-pool limit, used, reserved, and available values.
- [x] 2.2 Implement platform-authorized create/upsert of tenant total quotas with Bucket-capacity and lifecycle checks.
- [x] 2.3 Implement platform-authorized create/upsert of application reserved quotas with active-tenant/application validation and allocation-sum checks.
- [x] 2.4 Strengthen tenant and application quota updates so they cannot cross used, reserved, allocation-sum, or Bucket-capacity boundaries.
- [x] 2.5 Implement auditable revocation of application allocations; reject revocation when used or reserved bytes are non-zero unless an explicit migration/recovery policy applies.
- [x] 2.6 Ensure tenant members can read only active quotas in their tenant and cannot call platform allocation operations.

## 3. Platform API and contract

- [x] 3.1 Add platform quota list/detail schemas with tenant, application, allocation mode, lifecycle status, allocation totals, shared-pool values, and consistency metadata.
- [x] 3.2 Add `GET /api/v1/platform/quotas` with tenant/application/scope/status filters and stable pagination.
- [x] 3.3 Add `POST /api/v1/platform/quotas` for tenant-total and application-reserved allocation requests with stable validation errors.
- [x] 3.4 Add `PATCH /api/v1/platform/quotas/{quota_id}` with concurrency-safe allocation validation.
- [x] 3.5 Add `DELETE /api/v1/platform/quotas/{quota_id}` only for revoking eligible application allocations; keep tenant totals soft-managed.
- [x] 3.6 Update tenant-facing quota list/detail responses and metadata catalog enums; remove or mark storage-space quota allocation as legacy.
- [x] 3.7 Regenerate and validate `contracts/openapi.yaml`; verify every new, changed, and deprecated operation matches runtime responses.

## 4. Upload reservation and settlement

- [x] 4.1 Refactor direct-upload reservation to distinguish application-reserved mode from shared-pool mode.
- [x] 4.2 Refactor multipart reservation and part accounting to use the same allocation calculator and transaction lock order.
- [x] 4.3 Lock the tenant total and active application allocations consistently before checking shared-pool capacity.
- [x] 4.4 Settle successful uploads against tenant totals and the correct application/shared-pool usage; release failed, cancelled, and expired reservations exactly once.
- [x] 4.5 Ensure file deletion and replacement decrement the same quota dimensions that were incremented at completion.
- [x] 4.6 Add over-limit cleanup/isolation behavior when provider actual size exceeds declared or available capacity.

## 5. Reconciliation and lifecycle integration

- [x] 5.1 Reconcile shared-Bucket objects by tenant/application namespace and calculate tenant total, independent application, and shared-pool usage separately.
- [x] 5.2 Exclude suspended/deleted tenants and applications from effective quota calculations while reporting historical objects as auditable differences.
- [x] 5.3 Make reconciliation compare active application allocation sum with tenant capacity and report allocation drift.
- [x] 5.4 Integrate tenant/application lifecycle transitions with quota status and prevent new reservations for inactive owners.
- [x] 5.5 Add idempotent audit/apply reconciliation tests without modifying unrelated tenant allocations.

## 6. Verification and deployment

- [x] 6.1 Add service and repository tests for allocation boundaries, shared-pool consumption, revocation, and concurrent updates.
- [x] 6.2 Add HTTP tests for platform permission enforcement, schema shapes, filters, pagination, and stable error codes.
- [x] 6.3 Add end-to-end tests covering a shared Bucket, one tenant, one reserved application, and multiple shared applications.
- [x] 6.4 Run migration, OpenAPI, Ruff, Mypy, unit, integration, and container-level tests; record known external S3 limitations.
- [x] 6.5 Document rollout order, legacy quota handling, Bucket capacity configuration, and rollback behavior.
