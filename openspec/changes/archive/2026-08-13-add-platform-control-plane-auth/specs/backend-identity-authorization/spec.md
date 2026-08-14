## ADDED Requirements

### Requirement: Account and tenant sessions remain distinct
The system SHALL validate global account sessions independently from tenant
sessions. A valid account session alone MUST NOT be treated as a tenant
PrincipalContext or confer tenant permissions.

#### Scenario: Logged-in account has no selected tenant
- **WHEN** an account session calls a tenant-scoped endpoint before selecting a tenant
- **THEN** the system SHALL reject the request as requiring tenant authentication
