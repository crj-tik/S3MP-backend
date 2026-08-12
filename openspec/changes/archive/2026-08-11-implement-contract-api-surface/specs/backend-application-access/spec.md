## ADDED Requirements

### Requirement: Application and API Key HTTP lifecycle
The service SHALL expose the declared application, ownership, and API Key lifecycle operations through authorized tenant-scoped HTTP endpoints, including issue, inspect, rotate, revoke, and one-time secret behavior.

#### Scenario: Revoked key secret lookup
- **WHEN** a client requests a secret for an issued, rotated, or revoked API Key after its one-time response
- **THEN** the service SHALL return `410 secret_not_retrievable` and SHALL not return the secret

### Requirement: Application lifecycle service coordination
Application and API Key operations SHALL execute through tenant-scoped application services that enforce ownership, credential status, scope intersection, idempotency, audit recording, and one-time-secret handling before exposing a response.

#### Scenario: API Key is issued
- **WHEN** an authorized principal requests a new API Key for an application it may manage
- **THEN** the lifecycle service SHALL persist only a secret verifier, record a redacted audit event, and return the raw secret only in the issuance response
