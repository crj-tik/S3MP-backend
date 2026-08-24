## 1. Platform role model

- [x] 1.1 Add `tenant-admin` to the platform role baseline/catalog alongside `platform_admin`, `platform_operator`, and `platform_auditor`.
- [x] 1.2 Extend platform role grant/revoke validation, audit output, and API contracts to accept `tenant-admin`.
- [x] 1.3 Preserve global-user assignment, expiry, status, and authorization-version invalidation for all platform roles.

## 2. Tenant authorization bridge

- [x] 2.1 Resolve effective platform roles for the authenticated global user without reading roles from another tenant.
- [x] 2.2 When the current tenant has an ACTIVE Membership and the user has platform `tenant-admin`, inject the complete tenant permission baseline for this tenant only.
- [x] 2.3 Include the derived source in authorization explanations and invalidate it on platform-role or Membership changes.
- [x] 2.4 Keep application Principal authorization indirect: resolve its bound membership/user in the current tenant and never grant it platform authority directly.

## 3. Remove legacy tenant-local path

- [x] 3.1 Stop creating or binding tenant-local `tenant-admin` during tenant creation.
- [x] 3.2 Remove startup reconciliation and storage-space auto-binding for legacy tenant-admin roles.
- [x] 3.3 Add a migration/data cleanup for existing tenant-local tenant-admin roles and bindings, preserving audit history.

## 4. Contract and verification

- [x] 4.1 Keep tenant permission catalogs free of `platform.*` permissions.
- [x] 4.2 Update OpenAPI and metadata contracts for platform `tenant-admin` grant/revoke and effective authorization state.
- [x] 4.3 Test platform grant + ACTIVE Membership can create roles and perform all tenant operations.
- [x] 4.4 Test no Membership, inactive Membership, and another tenant are denied.
- [x] 4.5 Test platform-role revoke/expiry immediately removes derived tenant permissions.
- [x] 4.6 Run migration, authorization, HTTP, OpenAPI, contract, and lint test suites.
