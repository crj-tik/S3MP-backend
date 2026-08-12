## ADDED Requirements

### Requirement: Durable application and API Key lifecycle
Application and API Key lifecycle operations SHALL use tenant-scoped durable persistence, enforce ownership and status transitions, and append redacted audit records for credential mutations.

#### Scenario: Cross-tenant API Key mutation
- **WHEN** a principal targets an API Key outside its tenant
- **THEN** the system SHALL return `resource_not_found` without mutating or exposing that key
