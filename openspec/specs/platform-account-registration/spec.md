# platform-account-registration Specification

## Purpose

Provide safe global account registration and identifier-based login for human users without granting tenant membership or platform privileges automatically.

## Requirements

### Requirement: Register a global platform account
The service SHALL accept a unique email, company employee number, display name and password at `POST /api/v1/account/register`, create one global account, and create no tenant membership, platform role or session.

#### Scenario: Successful registration
- **WHEN** a client submits valid account fields
- **THEN** the system SHALL hash the password, persist normalized identities, record an audit event and return only a safe account summary

#### Scenario: Duplicate identity
- **WHEN** the email or employee number is already registered
- **THEN** the system SHALL return the stable `409 account_already_exists` error without identifying which field matched

### Requirement: Registration cannot self-escalate
Registration SHALL NOT grant platform permissions, tenant access, API keys or storage access.

#### Scenario: New account calls platform management
- **WHEN** a newly registered account calls a platform-management operation without an independently granted role
- **THEN** the system SHALL deny the request through normal platform authorization
