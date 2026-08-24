## MODIFIED Requirements

### Requirement: Platform control-plane management APIs are contract-declared
The service SHALL publish stable, documented, cursor-paginated API operations for authorized platform account discovery, platform role and role-binding inspection, Support Access request inspection, platform audit inspection, and tenant member-candidate discovery. Each operation SHALL declare its required permission, request filters, response DTOs, pagination behavior, and standard error envelope in the runtime OpenAPI document and checked-in contract before release.

#### Scenario: Frontend renders the platform support queue
- **WHEN** the frontend reads the published OpenAPI contract
- **THEN** it SHALL find a documented paginated operation for listing Support Access requests with stable request identifiers and status fields required for approval or revocation

#### Scenario: Platform authorization is missing
- **WHEN** a caller invokes a platform control-plane management operation without the operation's required platform permission
- **THEN** the API SHALL return the standard authorization error envelope and SHALL not return any platform or tenant resource record

#### Scenario: Frontend renders member candidates
- **WHEN** the frontend reads the published OpenAPI contract
- **THEN** it SHALL find `GET /api/v1/member-candidates` with its `query` parameter, bounded result response, required membership-management permission, and candidate identity fields
