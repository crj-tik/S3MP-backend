## ADDED Requirements

### Requirement: Acknowledged outbox delivery
The service SHALL retain each enqueued external-operation event until a consumer acknowledges successful handling. Failed, leased, or abandoned delivery attempts MUST remain recoverable and MUST NOT silently discard the event.

#### Scenario: Consumer cannot acquire a delivery lease
- **WHEN** a consumer observes an event that is already leased by another consumer
- **THEN** the event SHALL remain available for its active lease holder or later recovery and SHALL not be discarded

#### Scenario: Consumer rejects a delivery
- **WHEN** a consumer negatively acknowledges an event
- **THEN** the service SHALL schedule the event for retry or durable dead-letter handling with failure metadata

### Requirement: Concurrent rate-limit enforcement
Rate-limit admission SHALL be atomic per configured scope so concurrent requests cannot exceed the configured limit because of a race between counting and recording an admission.

#### Scenario: Concurrent requests reach the limit
- **WHEN** concurrent requests contend for the final available rate-limit slot
- **THEN** at most one request SHALL be admitted for that slot
