## ADDED Requirements

### Requirement: Atomic application bootstrap
The service SHALL create an application and its initial owner as one tenant-scoped durable operation. A successful creation response MUST identify an application whose owner relationship is already persisted; a persistence failure MUST return an error without leaving an ownerless application visible.

#### Scenario: Initial owner is persisted with the application
- **WHEN** an authorized principal creates an application
- **THEN** the created application SHALL be retrievable in its tenant and SHALL have that principal recorded as its initial owner

#### Scenario: Owner persistence cannot be completed
- **WHEN** the initial owner relationship cannot be persisted
- **THEN** the service SHALL fail the create operation and SHALL NOT expose a partially created application
