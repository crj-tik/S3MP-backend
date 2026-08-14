## MODIFIED Requirements

### Requirement: Registration and identifier login are published in the API contract

The runtime OpenAPI schema and checked-in `contracts/openapi.yaml` SHALL describe the registration endpoint, canonical `identifier` login field, employee-number constraints, duplicate-account errors, and non-sensitive account response fields with identical Chinese descriptions.

#### Scenario: Frontend reads the contract

- **WHEN** the frontend loads Swagger or `contracts/openapi.yaml`
- **THEN** it SHALL be able to distinguish email login from employee-number login, know that registration does not select a tenant, and see that passwords and session values are never returned
