## ADDED Requirements

### Requirement: Platform role APIs expose tenant-admin as a peer platform role
Platform role grant, revoke, list, and metadata APIs SHALL expose `tenant-admin` alongside `platform_admin`, `platform_operator`, and `platform_auditor`. The grant target SHALL be a global user account and SHALL preserve status, expiry, audit, and authorization-version fields.

#### Scenario: Platform UI grants tenant-admin
- **WHEN** an authorized platform operator grants `tenant-admin` to a global user
- **THEN** the API SHALL persist a platform-scoped grant and return the role name and effective status

#### Scenario: Tenant-admin is not accepted as a tenant role
- **WHEN** a tenant role API receives `tenant-admin` as a tenant-local role name or permission scope
- **THEN** the API SHALL reject the request as a platform-role misuse

### Requirement: Tenant permission catalog is scope-filtered
The tenant authorization API SHALL publish a permission catalog containing only tenant-scoped permissions. The response SHALL omit all `platform.*` entries while preserving permission names, descriptions, resource types and delegation metadata for tenant role configuration.

#### Scenario: Codegen consumes tenant catalog
- **WHEN** a frontend loads `GET /api/v1/permission_catalog` from a tenant session
- **THEN** generated role choices SHALL contain no platform permission and SHALL include the documented tenant permission metadata

#### Scenario: Platform permission is submitted to tenant role creation
- **WHEN** a tenant role request includes a `platform.*` permission
- **THEN** the request SHALL be rejected as an invalid or non-tenant permission and SHALL not create or modify a role
