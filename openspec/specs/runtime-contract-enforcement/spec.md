## Purpose

Make the published API contract executable at runtime so clients can rely on every declared operation, security boundary, and response convention.

## Requirements

### Requirement: Runtime operation coverage
The service SHALL register exactly one authenticated or explicitly public runtime route for every OpenAPI operationId in the published `/api/v1` contract, and SHALL fail contract verification when a declared operation is missing or a registered public operation is undeclared.

#### Scenario: Declared operation is absent
- **WHEN** contract verification finds an operationId without a registered runtime route
- **THEN** verification SHALL fail and identify the missing operationId

### Requirement: Shared HTTP mutation semantics
The service SHALL enforce declared Idempotency-Key and If-Match requirements before invoking a mutating application operation, and SHALL return the canonical idempotency or ETag error when validation fails.

#### Scenario: Idempotency key is reused with changed input
- **WHEN** a principal reuses an Idempotency-Key for the same operation with a different request fingerprint
- **THEN** the service SHALL return `409 idempotency_key_reused` without repeating the mutation

### Requirement: Application-service execution boundary
Public routers SHALL only translate HTTP input and output; an application service receiving PrincipalContext SHALL perform tenant resource resolution, authorization, mutation semantics, and external-operation coordination. Public routers MUST NOT directly access ORM persistence or object storage.

#### Scenario: A file mutation is requested
- **WHEN** a client invokes a file mutation endpoint
- **THEN** the router SHALL delegate to an application service that performs authorization, persistence, and storage coordination before returning the contract response