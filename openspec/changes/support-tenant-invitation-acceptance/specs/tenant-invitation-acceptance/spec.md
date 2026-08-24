## Purpose

Allows an authenticated account to discover and accept tenant invitations while preserving tenant isolation and explicit membership state transitions.

## ADDED Requirements

### Requirement: Authenticated account can accept its tenant invitation
The system SHALL expose `POST /api/v1/auth/tenant-invitations/{membership_id}/accept` for an authenticated account and SHALL transition the addressed Membership from `invited` to `active` only when it belongs to that account and is currently eligible for acceptance.

#### Scenario: Accept invited membership
- **WHEN** an authenticated account accepts its unexpired invited membership
- **THEN** the system SHALL atomically set `membership_status` to `active` and return the updated AccountContext

#### Scenario: Accepting an ineligible membership
- **WHEN** the membership is unknown, belongs to another account, is not invited, or is expired/revoked
- **THEN** the system SHALL return a stable client error and SHALL NOT change membership state

#### Scenario: Repeated acceptance
- **WHEN** an account accepts a membership that is already active
- **THEN** the system SHALL return an idempotent success or the current AccountContext without creating a duplicate membership or session

### Requirement: Invitation acceptance honors browser mutation security
The acceptance endpoint SHALL require the account authentication and account-domain CSRF proof used by other authenticated account mutations.

#### Scenario: Missing CSRF proof
- **WHEN** a browser submits invitation acceptance without valid account CSRF proof
- **THEN** the system SHALL reject the request before changing the Membership
