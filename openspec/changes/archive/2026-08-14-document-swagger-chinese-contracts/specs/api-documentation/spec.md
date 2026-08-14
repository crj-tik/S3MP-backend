## Purpose

Provide complete, consistent Chinese documentation for every backend API so that
Swagger and the downloadable OpenAPI contract can be used directly for frontend integration.

## ADDED Requirements

### Requirement: Swagger presents complete Chinese API guidance
The service SHALL expose Chinese descriptions in Swagger for every public API operation, including its purpose, authorization context, path/query/header parameters, request fields, response fields, and state-changing consequences where applicable.

#### Scenario: Frontend opens an operation in Swagger
- **WHEN** a frontend developer opens any public operation in `/docs`
- **THEN** Swagger SHALL display a Chinese operation description and Chinese descriptions for every displayed input and response field

### Requirement: Shared API concepts use canonical Chinese terminology
The service SHALL use one canonical Chinese description for the same logical identifier, pagination field, concurrency header, authorization context, storage target, and request field wherever it appears in Swagger or the published contract.

#### Scenario: Same field appears in multiple operations
- **WHEN** a field such as `tenant_id`, `storage_space_id`, `cursor`, `limit`, `If-Match`, or `Idempotency-Key` appears in more than one operation
- **THEN** every occurrence SHALL have the same Chinese description and SHALL NOT redefine its semantics

### Requirement: Documentation does not reveal protected implementation detail
The service SHALL describe authentication, authorization, storage, and error behavior without including credentials, raw session values, physical provider object keys, or other secret operational details.

#### Scenario: Documenting credentialed operations
- **WHEN** Swagger describes an API Key, account session, storage connection, or presigned operation
- **THEN** the description SHALL explain the client-visible behavior without exposing secret values or internal infrastructure details
