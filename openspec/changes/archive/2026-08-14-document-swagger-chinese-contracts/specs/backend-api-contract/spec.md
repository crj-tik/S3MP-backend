## ADDED Requirements

### Requirement: Contract documentation remains synchronized with Swagger
The published `contracts/openapi.yaml` and runtime Swagger schema SHALL contain the same Chinese operation, parameter, request-field, and response-field descriptions for every public operation.

#### Scenario: Contract documentation is validated
- **WHEN** CI validates the runtime schema against the published OpenAPI contract
- **THEN** it SHALL reject missing or divergent required Chinese documentation metadata

### Requirement: CSRF documentation matches the enforced security domain
The runtime and published contract SHALL explain that account control-plane mutations use `s3mp_account_csrf`, while tenant-scoped mutations use `s3mp_csrf`. This rule SHALL remain valid when both account and tenant session cookies are present.

#### Scenario: Tenant mutation after tenant selection
- **WHEN** a browser has both `s3mp_account_session` and `s3mp_session` and sends a tenant-scoped mutation
- **THEN** the server SHALL validate `X-S3MP-CSRF` against `s3mp_csrf` and SHALL accept the request when they match

#### Scenario: Account mutation after tenant selection
- **WHEN** a browser has both sessions and sends an account control-plane mutation
- **THEN** the server SHALL validate `X-S3MP-CSRF` against `s3mp_account_csrf`
