## ADDED Requirements

### Requirement: Security controls precede file mutations
Every protected file route SHALL authenticate the caller and enforce declared authorization, idempotency, and optimistic-concurrency requirements before it calls a file application operation. The router SHALL not ignore supplied `Idempotency-Key` or `If-Match` headers.

#### Scenario: Mutation uses a reused idempotency key with different input
- **WHEN** a caller reuses an idempotency key for the same file mutation with a different canonical request fingerprint
- **THEN** the service SHALL return `409 idempotency_key_reused` and SHALL not repeat the mutation

#### Scenario: Delete uses a stale entity tag
- **WHEN** a caller requests a file deletion with a stale `If-Match` value
- **THEN** the service SHALL return the canonical ETag conflict response and SHALL not delete the object or its record
