## ADDED Requirements

### Requirement: Durable Redis coordination
The runtime SHALL use Redis-backed coordination for configured idempotency, rate-limit, and outbox workflows; process-local fallbacks SHALL be restricted to isolated tests or explicitly documented development modes.

#### Scenario: API process restarts after an idempotent mutation
- **WHEN** the same idempotency key is retried after an API process restart
- **THEN** the runtime SHALL retain the prior result or conflict state through its configured durable coordination store
