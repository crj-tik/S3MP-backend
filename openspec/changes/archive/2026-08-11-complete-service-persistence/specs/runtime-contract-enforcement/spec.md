## ADDED Requirements

### Requirement: Mutation policy is enforced before service execution
Mutating routes SHALL validate idempotency and ETag requirements before invoking their application service and SHALL preserve the registered error envelope.

#### Scenario: Idempotency key conflicts with a changed request
- **WHEN** a caller reuses an idempotency key with a different request fingerprint
- **THEN** the system SHALL return `idempotency_key_reused` without repeating the mutation
