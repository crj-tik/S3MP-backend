## ADDED Requirements

### Requirement: Role-binding scope filters preserve authorization boundaries
The role-binding list SHALL support filtering by `storage_space_id` while
retaining current-tenant isolation and existing role-binding visibility rules.
The filter SHALL match the binding's persisted logical storage-space scope and
MUST NOT treat a canonical path prefix alone as a match for another space.

#### Scenario: Authorized operator lists bindings for a space
- **WHEN** an authorized tenant operator requests role bindings with a valid storage-space identifier in the current tenant
- **THEN** the response SHALL contain only bindings scoped to that storage space

#### Scenario: Caller supplies another tenant's storage space
- **WHEN** a caller supplies a storage-space identifier that is not active and owned by the current tenant
- **THEN** the API SHALL return no cross-tenant binding records and SHALL not disclose the foreign resource
