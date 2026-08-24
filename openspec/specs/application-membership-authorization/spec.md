## Purpose

Defines the tenant-scoped delegation contract that lets an application use one active Membership's direct and group permissions without impersonating that user or crossing tenant boundaries.

## Requirements

### Requirement: Application has one tenant-local authorization representative
Each application SHALL have at most one effective authorization representative, and that representative SHALL be an active Membership in the same tenant. Cross-tenant or inactive bindings MUST be rejected, and replacement or revocation SHALL be auditable.

#### Scenario: Bind application to active membership
- **WHEN** a tenant operator binds an application to an active Membership in the same tenant
- **THEN** the service SHALL persist one effective representative binding and return a non-secret summary

#### Scenario: Reject cross-tenant membership
- **WHEN** a tenant operator supplies a Membership belonging to another tenant
- **THEN** the service SHALL reject the request without revealing foreign resource details

#### Scenario: Reject a second representative
- **WHEN** an application already has an effective representative and a second binding is requested
- **THEN** the service SHALL replace it only through an explicit audited rebind operation

### Requirement: Application requests resolve representative membership at authorization time
An application API-key request SHALL remain authenticated as the application principal, and the service SHALL resolve its current representative Membership at authorization time. Direct user bindings and group-derived bindings of that Membership MAY contribute permissions; an inactive, expired, revoked, or missing representative SHALL produce default deny.

#### Scenario: Representative grants file permission
- **WHEN** an application API key requests a file operation and its active representative has an applicable allow binding
- **THEN** the service SHALL evaluate that binding without changing the authenticated principal

#### Scenario: Representative lacks operation permission
- **WHEN** the API key scope permits an operation but the representative has no applicable permission
- **THEN** the service SHALL return `403 permission_denied` before calling object storage

#### Scenario: Representative is suspended
- **WHEN** the representative Membership is suspended, expired, or removed before a request
- **THEN** the service SHALL deny the request and invalidate queued work for that application

### Requirement: Effective application authorization is tenant-scoped and auditable
The effective application decision SHALL intersect API-key scopes, representative direct/group grants, storage-space and canonical-prefix scope, tenant governance, and operation allowlists. Deny SHALL take precedence, and explanations/audit records SHALL identify the application actor and delegated source without secrets.

#### Scenario: Same user belongs to multiple tenants
- **WHEN** the representative user has roles in multiple tenants
- **THEN** the application SHALL use only the Membership and bindings from its own tenant

#### Scenario: Group-derived permission is evaluated for representative
- **WHEN** the representative belongs to an enabled group with a matching scoped allow binding
- **THEN** the group permission SHALL contribute to the application decision only within that tenant and scope

#### Scenario: Explicit deny overrides representative allow
- **WHEN** an applicable representative direct or group allow is also matched by a deny binding
- **THEN** the service SHALL return DENY with stable reason and source information
