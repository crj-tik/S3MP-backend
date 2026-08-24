# platform-control-plane Specification

## Purpose

Provide a platform governance plane that manages tenant lifecycle without
silently bypassing the authorization or data boundaries of any tenant.

## Requirements

### Requirement: Platform authority is independent of tenant authority
The system SHALL assign platform roles directly to global user accounts and
SHALL NOT represent platform authority as a tenant principal, Membership, Role,
or RoleBinding. `platform_admin`, `platform_operator`, and `platform_auditor`
MUST NOT grant direct tenant access. The platform role `tenant-admin` is an
explicit exception: it SHALL grant complete tenant-scoped authority only when
the same user has an ACTIVE Membership in the current tenant and the request
supplies that tenant context. No platform role SHALL cross tenant boundaries
without the current tenant Membership check.

#### Scenario: Platform administrator requests tenant file data
- **WHEN** a platform administrator calls a tenant data-plane operation without a tenant-scoped grant
- **THEN** the system SHALL reject the request as unauthorized

#### Scenario: Tenant admin platform grant with active membership
- **WHEN** a global user has platform `tenant-admin`, an ACTIVE Membership in the current tenant, and requests a tenant operation
- **THEN** the system SHALL evaluate the user as having all tenant-scoped permissions for that tenant

#### Scenario: Tenant admin without membership
- **WHEN** a global user has platform `tenant-admin` but no ACTIVE Membership in the requested tenant
- **THEN** the system SHALL reject the tenant operation

#### Scenario: Tenant admin is isolated per tenant
- **WHEN** a user has an ACTIVE Membership in tenant A but not tenant B and requests tenant operations for both
- **THEN** the system SHALL allow derived tenant-admin authority only in tenant A and SHALL reject tenant B

#### Scenario: Tenant admin grant is revoked
- **WHEN** a platform operator revokes the user's platform `tenant-admin` grant
- **THEN** subsequent tenant authorization checks SHALL no longer derive tenant-admin permissions

### Requirement: Bootstrap first platform administrator
The system SHALL provide an audited bootstrap mechanism that creates the first
active platform administrator only when none exists. It MUST NOT expose a public
HTTP registration path for this privilege.

#### Scenario: Bootstrap is attempted after initialization
- **WHEN** an active platform administrator already exists
- **THEN** the bootstrap mechanism SHALL fail without creating another administrator

### Requirement: Tenant creation has an accountable initial administrator
The system SHALL create a tenant and its initial active Membership atomically. A
newly created tenant MUST NOT be left without an active Membership. If an
initial administrator grant is requested, it SHALL be created atomically and
SHALL include only tenant-scoped permissions; tenant creation MUST NOT
implicitly create or bind a tenant-local `tenant-admin` role.

#### Scenario: Initial administrator setup fails
- **WHEN** a tenant creation request cannot create its initial administrator grant
- **THEN** the system SHALL roll back tenant creation

#### Scenario: Tenant creation does not bootstrap tenant-local tenant-admin
- **WHEN** a tenant is created without an explicit initial administrator grant
- **THEN** the system SHALL create the tenant and Membership only and SHALL not create a tenant-local `tenant-admin` Role or RoleBinding

### Requirement: Platform tenant-admin is a peer global role
The platform role catalog and role-binding APIs SHALL expose `tenant-admin`
alongside `platform_admin`, `platform_operator`, and `platform_auditor`. The
grant target SHALL be a global user account and SHALL preserve status, expiry,
audit, and authorization-version semantics. `tenant-admin` SHALL NOT be
accepted as a tenant-local role.

#### Scenario: Platform UI grants tenant-admin
- **WHEN** an authorized platform operator grants `tenant-admin` to a global user
- **THEN** the API SHALL persist a platform-scoped grant and return the role name and effective status

#### Scenario: Tenant-admin is not accepted as a tenant role
- **WHEN** a tenant role API receives `tenant-admin` as a tenant-local role name or permission scope
- **THEN** the API SHALL reject the request as a platform-role misuse

### Requirement: Support access is explicit and temporary
The system SHALL require a reason, target tenant, approved duration, and audit
trail for platform-initiated support access. It SHALL expire automatically,
shall not include file-content access by default, and SHALL expose authorized
read operations for discovering and reviewing Support Access requests. An
approved request SHALL create only a temporary tenant Membership and a bounded
support RoleBinding; the requester MUST explicitly select the tenant before
receiving tenant-scoped access.

#### Scenario: Support access expires
- **WHEN** the approved support-access expiry is reached
- **THEN** the system SHALL revoke the effective tenant access, invalidate affected authorization state and tenant sessions, and record the expiry in the platform audit trail

#### Scenario: Authorized approver reviews a request
- **WHEN** a caller with platform Support Access read authority lists pending requests
- **THEN** the system SHALL return the request identifier, requester, target tenant, reason, expiry, and current approval state without exposing tenant file content or credentials

### Requirement: Scheduler health verifies expiry execution capability
The managed Support Access expiry scheduler SHALL provide a one-pass execution
mode suitable for deployment health checks. A healthy scheduler check SHALL
verify that it can initialize the configured persistence dependency and execute
the idempotent expiry pass; it SHALL NOT report healthy merely because a
container process exists.

#### Scenario: Scheduler loses database connectivity
- **WHEN** the scheduler health check runs while its configured persistence dependency is unreachable
- **THEN** the health check SHALL fail so orchestration can mark the scheduler unhealthy

### Requirement: Platform role baselines include explicit read authority
The system SHALL grant each built-in platform role every explicit platform read
permission required by its declared operational responsibilities. A platform
administrator SHALL have tenant lifecycle read authority in addition to tenant
lifecycle management authority. Baseline reconciliation SHALL add newly
required permissions to existing built-in role records without removing
previously granted built-in permissions or changing custom roles.

#### Scenario: Existing platform administrator reads tenant inventory
- **WHEN** a database already contains an active built-in platform administrator role before a newly required tenant-read permission is introduced
- **THEN** baseline reconciliation SHALL add the permission and an administrator with that role SHALL be allowed to list platform tenants
