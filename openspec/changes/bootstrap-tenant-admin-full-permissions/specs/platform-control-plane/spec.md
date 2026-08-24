## MODIFIED Requirements

### Requirement: Platform authority is independent of tenant authority
The system SHALL assign platform roles directly to global user accounts and SHALL NOT represent platform authority as a tenant principal, Membership, Role, or RoleBinding. `platform_admin`, `platform_operator`, and `platform_auditor` MUST NOT grant direct tenant access. The platform role `tenant-admin` is an explicit exception: it SHALL grant complete tenant-scoped authority only when the same user has an ACTIVE Membership in the current tenant and the request supplies that tenant context. No platform role SHALL cross tenant boundaries without the current tenant Membership check.

#### Scenario: Platform administrator requests tenant file data
- **WHEN** a platform administrator calls a tenant data-plane operation without a tenant-scoped grant
- **THEN** system SHALL reject the request as unauthorized even though the user has a platform role

#### Scenario: Tenant admin platform grant with active membership
- **WHEN** a global user has platform `tenant-admin`, an ACTIVE Membership in the current tenant, and requests a tenant operation
- **THEN** system SHALL evaluate the user as having all tenant-scoped permissions for that tenant

#### Scenario: Tenant admin without membership
- **WHEN** a global user has platform `tenant-admin` but no ACTIVE Membership in the requested tenant
- **THEN** system SHALL reject the tenant operation

#### Scenario: Tenant admin is isolated per tenant
- **WHEN** a user has an ACTIVE Membership in tenant A but not tenant B and requests tenant operations for both
- **THEN** system SHALL allow derived tenant-admin authority only in tenant A and SHALL reject tenant B

#### Scenario: Tenant admin grant is revoked
- **WHEN** a platform operator revokes the user's platform `tenant-admin` grant
- **THEN** subsequent tenant authorization checks SHALL no longer derive tenant-admin permissions

### Requirement: Tenant creation has an accountable initial administrator
The system SHALL create a tenant and its initial active Membership atomically. A newly created tenant MUST NOT be left without an active Membership. If an initial administrator grant is requested, it SHALL be created atomically and SHALL include only tenant-scoped permissions; tenant creation MUST NOT implicitly create or bind a tenant-local `tenant-admin` role.

#### Scenario: Initial administrator setup succeeds
- **WHEN** a platform operator creates a tenant with an active initial administrator
- **THEN** the transaction SHALL create the tenant, membership, complete tenant-admin role and role binding atomically

#### Scenario: Initial administrator setup fails
- **WHEN** a tenant creation request cannot create its initial administrator grant
- **THEN** the system SHALL roll back tenant creation

#### Scenario: Existing tenant baseline is upgraded
- **WHEN** the service starts with an existing tenant whose built-in tenant-admin role lacks newly catalogued tenant permissions
- **THEN** baseline reconciliation SHALL add the missing tenant permissions without modifying custom roles or adding platform permissions

#### Scenario: Tenant creation does not bootstrap tenant-local tenant-admin
- **WHEN** a tenant is created without an explicit initial administrator grant
- **THEN** the system SHALL create the tenant and Membership only and SHALL not create a tenant-local `tenant-admin` Role or RoleBinding

## ADDED Requirements

### Requirement: Tenant permission catalog excludes platform permissions
The tenant-scoped permission catalog SHALL return only permissions whose names do not begin with `platform.`. Platform permissions SHALL be exposed only through platform control-plane authorization and SHALL NOT be valid choices in tenant role forms.

#### Scenario: Tenant role form loads permission catalog
- **WHEN** an authenticated tenant principal requests the tenant permission catalog
- **THEN** every returned permission SHALL be tenant-scoped and no `platform.*` item SHALL be present
