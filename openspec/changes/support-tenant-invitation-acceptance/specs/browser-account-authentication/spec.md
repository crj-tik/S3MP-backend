## MODIFIED Requirements

### Requirement: Explicit tenant-session selection
The system SHALL allow an account session to create a tenant session only for an active, unexpired Membership selected by the user. Account context SHALL expose every tenant Membership belonging to the account that is either active or invited, and each tenant entry SHALL include `id`, `name`, `slug`, `membership_id`, and `membership_status`.

#### Scenario: User selects an active tenant
- **WHEN** an authenticated account selects a tenant with an active Membership
- **THEN** the system SHALL establish a tenant session that resolves to that Membership

#### Scenario: User selects an inaccessible tenant
- **WHEN** an authenticated account selects a tenant without an active Membership
- **THEN** the system SHALL reject the request without establishing a tenant session

#### Scenario: Account context includes invited tenant
- **WHEN** an authenticated account requests `GET /api/v1/auth/me` and has an invited Membership
- **THEN** the response SHALL include that tenant with its `membership_id` and `membership_status: "invited"` alongside active memberships
