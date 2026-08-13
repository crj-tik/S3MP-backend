## Purpose

Make the published API contract executable at runtime so clients can rely on every declared operation, security boundary, and response convention.

## Requirements

### Requirement: Runtime operation coverage
The service SHALL register exactly one authenticated or explicitly public runtime route for every OpenAPI operationId in the published `/api/v1` contract, and SHALL fail contract verification when a declared operation is missing, a registered public operation is undeclared, or a declared `x-permission` is absent from the runtime authorization classification.

#### Scenario: Declared operation is absent
- **WHEN** contract verification finds an operationId without a registered runtime route
- **THEN** verification SHALL fail and identify the missing operationId

#### Scenario: Declared permission has no runtime enforcement classification
- **WHEN** contract verification finds a non-public operation with `x-permission` that is not classified as a machine-resource or management operation and not bound to runtime authorization
- **THEN** verification SHALL fail and identify the operationId and declared permission

### Requirement: Shared HTTP mutation semantics
The service SHALL enforce declared Idempotency-Key and If-Match requirements before invoking a mutating application operation, and SHALL return the canonical idempotency or ETag error when validation fails.

#### Scenario: Idempotency key is reused with changed input
- **WHEN** a principal reuses an Idempotency-Key for the same operation with a different request fingerprint
- **THEN** the service SHALL return `409 idempotency_key_reused` without repeating the mutation

### Requirement: Application-service execution boundary
Public routers SHALL only translate HTTP input and output; an application service receiving PrincipalContext SHALL perform tenant resource resolution, authorization, mutation semantics, and external-operation coordination. Public routers MUST NOT directly access ORM persistence or object storage. Services for contract-declared permissioned operations SHALL recheck the declared permission or an equivalent resource-specific decision when invoked outside HTTP routing.

#### Scenario: A file mutation is requested
- **WHEN** a client invokes a file mutation endpoint
- **THEN** the router SHALL delegate to an application service that performs authorization, persistence, and storage coordination before returning the contract response

#### Scenario: Permissioned service is called without its router
- **WHEN** an internal caller invokes a permissioned storage, quota, audit, identity, authorization, application, or API-Key service method directly
- **THEN** the service SHALL reject a context that lacks the required effective permission before reading or mutating the target resource
