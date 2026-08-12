## ADDED Requirements

### Requirement: Durable tenant-scoped identity administration
Member, group, role binding, and authorization-version operations SHALL use tenant-scoped persistence and conceal resources outside the caller's tenant.

#### Scenario: Membership lifecycle changes
- **WHEN** an administrator suspends or removes a membership
- **THEN** the system SHALL advance authorization version and invalidate affected active sessions
