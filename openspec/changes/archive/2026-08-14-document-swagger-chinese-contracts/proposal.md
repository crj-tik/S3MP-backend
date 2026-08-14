## Why

The deployed Swagger UI exposes all runtime endpoints but provides only generated titles, forcing frontend developers to infer endpoint intent and request semantics from implementation. Chinese descriptions and stable terminology are needed before the backend contract is handed to the frontend for real integration.

## What Changes

- Add a backend-owned Chinese API documentation capability for Swagger and the published OpenAPI contract.
- Describe every public operation, path/query/header parameter, request field, and response field in Chinese.
- Establish one canonical glossary so the same identifier and payload field always has the same meaning across operations.
- Make runtime Swagger and `contracts/openapi.yaml` consume the same documentation metadata, with automated completeness and consistency checks.
- Correct the documented and enforced CSRF security boundary when an account session and a tenant session coexist.

## Capabilities

### New Capabilities
- `api-documentation`: Chinese, contract-aligned operation and parameter documentation published through Swagger and OpenAPI.

### Modified Capabilities
- `backend-api-contract`: Published API contract must include complete Chinese descriptions and remain synchronized with runtime Swagger.

## Impact

Affected areas include OpenAPI generation, `contracts/openapi.yaml`, shared API schemas and parameters, Swagger UI rendering, contract validation, browser CSRF middleware, cookie configuration, and frontend integration documentation. No endpoint paths or request payload formats change.
