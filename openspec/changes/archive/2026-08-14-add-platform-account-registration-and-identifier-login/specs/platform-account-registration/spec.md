## ADDED Requirements

### Requirement: Register a global platform account

The service SHALL expose `POST /api/v1/account/register` accepting a unique email, unique company employee number, display name, and password, and SHALL create one global user account without creating tenant membership or platform-role bindings.

#### Scenario: Successful registration

- **WHEN** a client submits valid email, employee number, display name, and password
- **THEN** the service SHALL hash the password with the existing password hasher, persist the normalized identity values, return the new non-sensitive account summary, and SHALL NOT return the password or establish a session automatically

#### Scenario: Duplicate identity

- **WHEN** the email or employee number already belongs to an account
- **THEN** the service SHALL reject the request with a stable conflict error and SHALL NOT reveal which identity field matched beyond the documented duplicate-account error

#### Scenario: Invalid registration data

- **WHEN** email, employee number, display name, or password violates the documented format or length constraints
- **THEN** the service SHALL reject the request before persistence and SHALL not create a partial account

### Requirement: Employee number is a global login identity

The service SHALL store a normalized company employee number with a unique constraint for non-null values, preserve existing accounts that do not yet have an employee number, and SHALL never use the raw value as a password or credential secret.

#### Scenario: Existing account migration

- **WHEN** the schema migration runs against existing user accounts
- **THEN** existing accounts SHALL remain usable, their employee number SHALL be nullable until completed by an authorized account-management flow, and duplicate non-null values SHALL be rejected

### Requirement: Login by email or employee number

The service SHALL allow `POST /api/v1/account/login` to authenticate with an `identifier` containing either a normalized email or employee number plus a password. A deprecated email-only compatibility field MAY be accepted during migration, but the request SHALL reject ambiguous or conflicting identifier input.

#### Scenario: Email login

- **WHEN** a valid email and password are supplied as the identifier
- **THEN** the service SHALL establish the existing account session and return the account summary without selecting a tenant

#### Scenario: Employee-number login

- **WHEN** a valid employee number and password are supplied as the identifier
- **THEN** the service SHALL establish the same account-session behavior as email login

#### Scenario: Authentication failure

- **WHEN** the identifier is unknown, the password is incorrect, or the account is unusable
- **THEN** the service SHALL return the same generic authentication failure, apply the existing rate limiter, and SHALL not disclose whether the email or employee number exists

### Requirement: Registration cannot self-escalate

The service SHALL NOT grant a platform role, tenant membership, tenant session, API key, storage access, or other authorization solely because an account was registered.

#### Scenario: Newly registered account attempts platform control

- **WHEN** a newly registered account calls a platform-management operation without an independently granted platform role
- **THEN** the request SHALL be denied by the existing platform authorization checks and SHALL be auditable
