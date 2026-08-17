## Purpose

Provide a discoverable, least-privilege platform administration workflow for
global accounts and tenants without bypassing tenant authorization boundaries.

## Requirements

### Requirement: Platform administrators can discover global management subjects
The system SHALL expose a paginated platform-account directory for authorized platform users to select active global accounts when assigning a platform role or choosing a tenant's initial administrator. The directory SHALL support exact identifier lookup by email or employee number and return only safe account fields; it SHALL NOT return password hashes, session data, API keys, or tenant-scoped permissions.

#### Scenario: Platform administrator selects an initial tenant administrator
- **WHEN** a caller with platform account-directory permission searches an active account by employee number
- **THEN** the system SHALL return the matching safe account summary including its global user identifier

#### Scenario: Unauthorized account-directory request
- **WHEN** a caller without platform account-directory permission requests the account directory
- **THEN** the system SHALL reject the request without returning global account records

### Requirement: Platform control-plane resources are discoverable and pageable
The system SHALL expose authorized, cursor-paginated read operations for platform roles, platform role bindings, Support Access requests, and platform audit events. Each returned record SHALL include the stable identifier needed for a permitted follow-up operation and preserve the standard public error envelope.

#### Scenario: Approver discovers pending support requests
- **WHEN** an authorized approver lists Support Access requests filtered to pending state
- **THEN** the system SHALL return request identifiers, requester summaries, target-tenant summaries, reasons, expiry times, and approval state without exposing tenant file contents or credentials

#### Scenario: Platform role administrator revokes a discovered binding
- **WHEN** an authorized platform role administrator lists active platform role bindings and revokes one returned binding identifier
- **THEN** the system SHALL revoke that binding and record a platform audit event

### Requirement: Support access leads to explicit bounded tenant entry
The system SHALL require approved Support Access to materialize a temporary active Membership and time-bounded read-only tenant role. The requester SHALL obtain tenant data access only by explicitly selecting that tenant through the normal tenant-session operation; platform authority alone SHALL NOT create a tenant data context.

#### Scenario: Approved support requester enters a tenant
- **WHEN** a Support Access request has been approved and has not expired
- **THEN** the requester SHALL be able to select the approved tenant and receive only the permissions granted by the time-bounded support role

#### Scenario: Platform administrator skips support approval
- **WHEN** a platform administrator without an active tenant Membership calls a tenant-scoped management or file operation
- **THEN** the system SHALL reject the call without disclosing tenant data

### Requirement: Support access expiry is operated as a managed lifecycle
The deployment SHALL invoke Support Access expiry processing on a bounded recurring schedule. Once an approved request expires or is revoked, the system SHALL revoke the materialized tenant Membership, support RoleBinding, and unrevoked tenant sessions bound to that Membership, and SHALL create a platform audit event.

#### Scenario: Support grant reaches expiry
- **WHEN** the managed expiry processor observes an approved Support Access request at or past its expiry time
- **THEN** it SHALL revoke the request's effective tenant access before the next scheduled interval completes

### Requirement: Platform tenant lifecycle responses are explicit
The platform tenant list SHALL return a cursor-paginated `items` collection of stable tenant resource responses. Tenant detail and update operations SHALL return the same explicit resource shape, including identifier, slug, name, lifecycle status, and creation timestamp. Platform tenant responses MUST NOT use `unknown` or a request-body DTO as their response model.

#### Scenario: Frontend lists platform tenants
- **WHEN** an authorized platform administrator requests the platform tenant list
- **THEN** the API SHALL return `{items, next_cursor}` with each item containing `id`, `slug`, `name`, `status`, and `created_at`

#### Scenario: Frontend updates a platform tenant
- **WHEN** an authorized platform administrator updates a tenant name or status
- **THEN** the API SHALL return the updated `PlatformTenantResponse` resource rather than the submitted update request body

### Requirement: Platform role and support access queues are queryable
The platform control plane SHALL expose cursor-paginated list operations for platform role bindings and Support Access requests. Responses SHALL include stable identifiers, safe subject summaries, lifecycle state, and fields needed by an authorized operator to approve, revoke, or inspect a record.

#### Scenario: Operator loads role bindings
- **WHEN** a caller with platform role read permission lists platform role bindings
- **THEN** the API SHALL return a paginated collection containing each binding identifier, subject, role, expiry, and revocation state

#### Scenario: Operator loads support access queue
- **WHEN** a caller with Support Access read permission lists support requests
- **THEN** the API SHALL return a paginated collection with requester, target tenant, reason, expiry, and `pending`, `approved`, `revoked`, or `expired` state

### Requirement: Control-plane pagination and operation attribution are exact
Platform tenant and platform-role inventories SHALL use the same bounded cursor-paginated read contract as other control-plane lists. Repository filtering SHALL occur before page sizing. Each control-plane route SHALL bind its authorization dependency to that route's exact documented operation identifier, even when another route uses the same platform permission.

#### Scenario: Tenant inventory exceeds one page
- **WHEN** an authorized caller requests platform tenants with a limit smaller than the inventory
- **THEN** the API SHALL return the first deterministic page and a cursor that returns the next page without duplicates or omissions

#### Scenario: Contract verifier inspects shared-permission routes
- **WHEN** two control-plane routes require the same platform permission
- **THEN** each route SHALL still expose its own exact operation identifier to contract verification
