## MODIFIED Requirements

### Requirement: Global identity has an employee number

The global user identity SHALL expose a non-secret company employee number when present, enforce uniqueness across the global account table, and SHALL keep that identity separate from tenant membership, roles, and permissions.

#### Scenario: Identity is shown in account context

- **WHEN** an authenticated account requests its account context
- **THEN** the response SHALL include email, employee number, display name, and user identifier without password hash or session material
