## ADDED Requirements

### Requirement: Platform control-plane management APIs are contract-declared
The service SHALL publish stable, documented, cursor-paginated API operations
for authorized platform account discovery, platform role and role-binding
inspection, Support Access request inspection, and platform audit inspection.
Each operation SHALL declare its required platform permission, request filters,
response DTOs, pagination behavior, and standard error envelope in the runtime
OpenAPI document and checked-in contract before release.

#### Scenario: Frontend renders the platform support queue
- **WHEN** the frontend reads the published OpenAPI contract
- **THEN** it SHALL find a documented paginated operation for listing Support Access requests with stable request identifiers and status fields required for approval or revocation

#### Scenario: Platform authorization is missing
- **WHEN** a caller invokes a platform control-plane management operation without the operation's required platform permission
- **THEN** the API SHALL return the standard authorization error envelope and SHALL not return any platform or tenant resource record

### Requirement: Platform and storage response schemas are explicit
The runtime application and checked-in OpenAPI contract SHALL declare explicit
response schemas for platform tenant list/detail/update operations, platform
role-binding and Support Access list operations, and storage connection probe
results. These operations MUST NOT expose `unknown` responses or reuse a
request-body schema as a semantically different response. The probe response
SHALL describe status, read/write capability, check time, and safe failure
information without exposing credentials or signing material.

#### Scenario: Contract exposes platform tenant resources
- **WHEN** the frontend generates types from the contract
- **THEN** tenant list, detail, and update operations SHALL resolve to `PlatformTenantPage` or `PlatformTenantResponse`, not `unknown` or `TenantUpdate`

#### Scenario: Contract exposes probe results
- **WHEN** the frontend invokes a storage connection probe
- **THEN** the response SHALL resolve to a dedicated probe-result schema and SHALL not resolve to the probe request body

### Requirement: Platform list contracts perform filter-stable cursor pagination
Every platform list contract, including tenants and platform roles, SHALL
accept bounded cursor pagination and return only the matching records in its
`items` collection. A cursor SHALL be valid only for the operation and
normalized filter set for which it was issued. Lifecycle-status query
parameters SHALL accept only the documented values and reject unsupported
values as a validation error.

#### Scenario: Filtered support page has later matches
- **WHEN** more than `limit` earlier Support Access records do not match a requested lifecycle status and matching records exist after them
- **THEN** the returned page SHALL contain the earliest matching records and SHALL provide a next cursor whenever further matching records exist

#### Scenario: Caller reuses a cursor with different filters
- **WHEN** a caller presents an opaque platform-list cursor with a different query or lifecycle filter from the request that issued it
- **THEN** the API SHALL reject the cursor and SHALL not mix records from distinct result sets

### Requirement: Support Access responses identify safe approval subjects
An authorized Support Access list or detail response SHALL include a safe
approver account summary when the request has been approved, in addition to
the existing approver identifier. The summary SHALL use the same safe account
fields as requester summaries and SHALL omit credentials, sessions, and
tenant-scoped permissions.

#### Scenario: Operator reviews an approved request
- **WHEN** an authorized operator retrieves an approved Support Access request
- **THEN** the response SHALL include both the requester summary and the safe approver summary
