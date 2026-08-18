# browser-account-authentication Specification

## Purpose

Allow a human account to authenticate in a browser, select an authorized tenant,
and obtain bounded sessions without exposing credentials or raw session tokens.

## Requirements

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
The public account login and public account registration endpoints SHALL be
exempt from CSRF validation because they do not require an existing browser
session.

#### Scenario: Cross-site mutation lacks CSRF proof
- **WHEN** a browser session submits an unsafe request without valid CSRF proof
- **THEN** the system SHALL reject it before mutating state

#### Scenario: Public registration with no browser session
- **WHEN** an unauthenticated client submits a valid account registration request
- **THEN** the system SHALL process registration without requiring a CSRF cookie or `X-S3MP-CSRF` header

#### Scenario: Public registration with stale browser cookies
- **WHEN** a client submits a valid account registration request while carrying a stale account or tenant session cookie
- **THEN** the system SHALL not reject the request solely because CSRF proof is absent for that public registration endpoint

#### Scenario: Authenticated account mutation remains protected
- **WHEN** a browser session submits logout, tenant selection, platform management, or another unsafe authenticated request without the CSRF proof for its security domain
- **THEN** the system SHALL reject the request before mutating state

### Requirement: Account login accepts email or employee number
The system SHALL authenticate an active global user using either a normalized email or company employee number, while preserving a bounded compatibility path for existing email-only clients.

#### Scenario: Employee-number login
- **WHEN** an active user submits a valid employee number and password
- **THEN** the system SHALL create the same account session as email login without selecting a tenant

### Requirement: CSRF token transport is explicit
The system SHALL issue a readable CSRF cookie alongside each browser session and SHALL require the value belonging to the request's security domain in the `X-S3MP-CSRF` header for unsafe authenticated requests. Account control-plane mutations SHALL use `s3mp_account_csrf`; tenant-scoped mutations SHALL use `s3mp_csrf` when a tenant session exists.

#### Scenario: Account logout CSRF proof
- **WHEN** the frontend sends account logout with the value of `s3mp_account_csrf` in `X-S3MP-CSRF`
- **THEN** the system SHALL validate the matching account session and revoke it; tenant-session mutations SHALL use `s3mp_csrf` instead

#### Scenario: Tenant mutation after account login
- **WHEN** a browser has both account and tenant sessions and sends a tenant-scoped mutation with `s3mp_csrf`
- **THEN** the system SHALL validate the tenant CSRF token rather than preferring the account CSRF token
