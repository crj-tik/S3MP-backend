## ADDED Requirements

### Requirement: Complete identity and authorization HTTP operations
The service SHALL expose the contract-declared member detail, group membership, effective-permission, and authorization-simulation operations through authenticated tenant-scoped HTTP endpoints.

#### Scenario: Effective permissions for another tenant principal
- **WHEN** an authenticated principal requests effective permissions for an identifier outside its tenant
- **THEN** the service SHALL return `404 resource_not_found` without revealing cross-tenant existence
