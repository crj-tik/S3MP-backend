## Purpose

Provide durable coordination across database state, object storage, quotas, and audit records so externally visible service outcomes are recoverable and safe.

## ADDED Requirements

### Requirement: Recoverable external-operation lifecycle
Every mutating operation that invokes object storage SHALL durably record an intent before the external call and SHALL persist a completed, failed, or partial-failure outcome after verification.

#### Scenario: Persistence fails after a verified storage operation
- **WHEN** object storage succeeds but final database settlement fails
- **THEN** the system SHALL retain a recoverable pending operation without reporting unverified success

### Requirement: High-risk audit closure
High-risk credential, quota, signature, copy, move, and delete operations SHALL record redacted audit intent before success and SHALL return `audit_unavailable` when that write cannot be made durable.

#### Scenario: Audit storage is unavailable
- **WHEN** a caller requests a high-risk mutation while audit persistence fails
- **THEN** the system SHALL reject the mutation before invoking its externally visible action
