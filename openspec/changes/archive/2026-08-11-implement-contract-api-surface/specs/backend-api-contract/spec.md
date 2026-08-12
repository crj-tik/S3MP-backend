## ADDED Requirements

### Requirement: Executable public API baseline
Every OpenAPI operation declared in the backend-owned contract SHALL be executable through the runtime application and SHALL preserve its declared path, method, required parameters, response status, and stable error envelope.

#### Scenario: Frontend invokes a declared API Key list operation
- **WHEN** a client calls `GET /applications/{application_id}/api_keys` with a valid tenant context
- **THEN** the runtime route SHALL serve that exact path and SHALL NOT require or expose an alternate global API-key list path

### Requirement: Contract-aligned error vocabulary
The runtime service SHALL emit only error codes registered in the backend error catalog for public API failures.

#### Scenario: Authentication is missing or unusable
- **WHEN** a protected operation has no valid authentication context
- **THEN** the service SHALL return `401 authentication_required`
