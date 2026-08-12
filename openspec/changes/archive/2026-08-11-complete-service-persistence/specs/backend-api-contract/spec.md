## ADDED Requirements

### Requirement: Configured service execution
Every declared public operation SHALL be backed by a configured application service and tenant-scoped persistence adapter; no runtime route SHALL delegate to a placeholder implementation.

#### Scenario: A service dependency is absent
- **WHEN** startup composes a registered route without its required service dependency
- **THEN** readiness SHALL fail before the application reports ready
