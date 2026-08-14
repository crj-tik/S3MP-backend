## Why

The backend currently authenticates existing global accounts but has no supported account creation API, and login accepts email only. The frontend needs a real platform-account lifecycle with email, company employee number, name, password, and login by either email or employee number.

## What Changes

- Add public platform-account registration for a global user account.
- Add a unique company employee number to the global account model, with safe normalization and migration compatibility for existing accounts.
- Extend account login to accept either email or employee number while preserving a controlled compatibility path for existing email clients.
- Return the non-sensitive account identity fields needed by the frontend, never password material or session secrets.
- Keep registration separate from platform administration: a newly registered account receives no platform role and no tenant membership unless an authorized flow grants it.
- Add rate limiting, audit events, duplicate-account handling, and contract/OpenAPI documentation.

## Capabilities

### New Capabilities

- `platform-account-registration`: Global account creation, employee-number identity, and identifier-based account login.

### Modified Capabilities

- `browser-account-authentication`: Account login accepts a normalized email or employee number and exposes the registered account summary.
- `backend-identity-authorization`: Global user identity includes a unique employee number without changing tenant isolation or granting permissions.
- `backend-api-contract`: Add registration and updated login DTOs, error semantics, and Chinese Swagger documentation.

## Impact

Affected areas include the identity database model and migration, platform repository and authentication service, account router and schemas, password/rate-limit handling, audit logging, OpenAPI contract, contract checks, and unit/integration tests. No S3, Redis, or file authorization behavior changes.
