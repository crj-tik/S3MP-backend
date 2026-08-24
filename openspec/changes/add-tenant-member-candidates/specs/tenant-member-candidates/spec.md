## Purpose

Provides tenant administrators with a safe, tenant-scoped directory of globally registered users who can still be invited into the current tenant.

## ADDED Requirements

### Requirement: Tenant administrator can search member candidates
The system SHALL expose `GET /api/v1/member-candidates` to callers authorized to manage memberships. It SHALL return active globally registered users who have no Membership record in the current tenant, with only `id`, `email`, and `display_name` fields.

#### Scenario: Search by email, name, or employee number
- **WHEN** an authorized caller supplies a non-blank `query` value
- **THEN** the system SHALL perform one case-insensitive fuzzy match across email, display name, and employee number and return only users not already associated with the current tenant

#### Scenario: Empty candidate search
- **WHEN** an authorized caller omits `query` or supplies only whitespace
- **THEN** the system SHALL return the bounded, deterministically ordered set of active globally registered users with no Membership record in the current tenant

#### Scenario: Existing membership is excluded
- **WHEN** a user has any Membership record in the current tenant, regardless of whether its status is invited, active, suspended, or removed
- **THEN** the system SHALL exclude that user from candidate results even when the query matches

#### Scenario: Tenant isolation
- **WHEN** a user belongs to another tenant but has no Membership in the current tenant
- **THEN** the system SHALL include that user if the global account is active and the query matches, without exposing any foreign membership data

#### Scenario: Missing membership-management permission
- **WHEN** a caller lacks the current tenant's membership-management permission
- **THEN** the system SHALL reject the request with the standard authorization error envelope
