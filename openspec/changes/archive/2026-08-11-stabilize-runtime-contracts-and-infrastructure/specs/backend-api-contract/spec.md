## ADDED Requirements

### Requirement: Canonical public path base
The published backend OpenAPI contract SHALL use `/api/v1` as the canonical path base for every public operation, and runtime operations SHALL preserve those exact paths and methods.

#### Scenario: Client invokes a documented operation
- **WHEN** a client calls an operation at its published `/api/v1` path
- **THEN** the runtime SHALL register and serve that same path without requiring an undocumented alternative path

### Requirement: Catalogued one-time-secret response
When a caller attempts to retrieve an API Key secret after its one-time issuance response, the service SHALL return `410 secret_not_retrievable` using the standard error envelope.

#### Scenario: Secret is requested again
- **WHEN** a caller requests an issued API Key secret after issuance
- **THEN** the response SHALL have status `410` and error code `secret_not_retrievable`, and SHALL not include the secret
