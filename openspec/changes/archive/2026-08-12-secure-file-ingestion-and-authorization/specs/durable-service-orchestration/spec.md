## ADDED Requirements

### Requirement: Recoverable ingestion commitment
The service SHALL persist ingestion intent before object-storage work and SHALL append verified, committed, failed, expired, or reconciliation-required lifecycle events. A storage success followed by persistence or settlement failure MUST remain recoverable and MUST NOT be reported as a successful available file.

#### Scenario: Database settlement fails after object verification
- **WHEN** an object is verified in storage but the ingestion commit, quota settlement, or audit linkage cannot be made durable
- **THEN** the service SHALL persist or recover a reconciliation-required state and SHALL not report successful ingestion

### Requirement: Idempotent ingestion settlement
The service SHALL correlate an ingestion attempt with a tenant-scoped idempotency key, request identifier, session identity, and verified provider object identity. Retried completion or recovery MUST NOT create duplicate file objects, ingestion records, quota settlements, or audit events.

#### Scenario: Completion request is retried
- **WHEN** a caller retries the same completion after an ambiguous network or persistence outcome
- **THEN** the service SHALL return the previously established result or resume reconciliation without duplicating durable effects
