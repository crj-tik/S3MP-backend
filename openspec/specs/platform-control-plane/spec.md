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
