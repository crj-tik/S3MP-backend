## Purpose

Allow a human account to authenticate in a browser, select an authorized tenant,
and obtain bounded sessions without exposing credentials or raw session tokens.

## ADDED Requirements

### Requirement: Account login and logout
The system SHALL authenticate an active global user by supported credentials,
create an opaque account session, and set only secure cookie attributes suitable
for the configured environment. Login failures SHALL not reveal account existence.

#### Scenario: Valid local-password login
- **WHEN** an active user submits valid credentials within the rate limit
- **THEN** the system SHALL establish an account session and return account and accessible-tenant context without returning a raw token in JSON

#### Scenario: Invalid credentials
- **WHEN** a login attempt supplies an unknown account or invalid password
- **THEN** the system SHALL return the same registered authentication failure response

### Requirement: Explicit tenant-session selection
The system SHALL allow an account session to create a tenant session only for an
active, unexpired Membership selected by the user.

#### Scenario: User selects an active tenant
- **WHEN** an authenticated account selects a tenant with an active Membership
- **THEN** the system SHALL establish a tenant session that resolves to that Membership

#### Scenario: User selects an inaccessible tenant
- **WHEN** an authenticated account selects a tenant without an active Membership
- **THEN** the system SHALL reject the request without establishing a tenant session

### Requirement: Browser mutation protection
The system SHALL protect browser-authenticated unsafe requests with CSRF
validation. It SHALL issue secure cookies in production and allow non-secure
cookies only in the explicitly configured development environment.

#### Scenario: Cross-site mutation lacks CSRF proof
- **WHEN** a browser session submits an unsafe request without valid CSRF proof
- **THEN** the system SHALL reject it before mutating state
