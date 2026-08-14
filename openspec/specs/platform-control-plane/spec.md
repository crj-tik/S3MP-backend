# platform-control-plane Specification

## Purpose

Provide a platform governance plane that manages tenant lifecycle without
silently bypassing the authorization or data boundaries of any tenant.

## Requirements

### Requirement: Platform authority is independent of tenant authority
The system SHALL assign platform roles directly to global user accounts and
SHALL NOT represent platform authority as a tenant principal, Membership, Role,
or RoleBinding. Platform authority MUST NOT grant direct file, object-storage,
application API-Key, or tenant-management access.

#### Scenario: Platform administrator requests tenant file data
- **WHEN** a platform administrator calls a tenant data-plane operation without a tenant-scoped grant
- **THEN** the system SHALL reject the request as unauthorized

### Requirement: Bootstrap first platform administrator
The system SHALL provide an audited bootstrap mechanism that creates the first
active platform administrator only when none exists. It MUST NOT expose a public
HTTP registration path for this privilege.

#### Scenario: Bootstrap is attempted after initialization
- **WHEN** an active platform administrator already exists
- **THEN** the bootstrap mechanism SHALL fail without creating another administrator

### Requirement: Tenant creation has an accountable initial administrator
The system SHALL create a tenant, its initial active Membership, and the initial
tenant-administrator grant atomically. A newly created tenant MUST NOT be left
without an active tenant administrator.

#### Scenario: Initial administrator setup fails
- **WHEN** a tenant creation request cannot create its initial administrator grant
- **THEN** the system SHALL roll back tenant creation

### Requirement: Support access is explicit and temporary
The system SHALL require a reason, target tenant, approved duration, and audit
trail for platform-initiated support access. It SHALL expire automatically and
shall not include file-content access by default.

#### Scenario: Support access expires
- **WHEN** the approved support-access expiry is reached
- **THEN** the system SHALL revoke the effective tenant access and invalidate affected authorization state
