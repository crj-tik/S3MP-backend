## 1. Data model and migration

- [x] 1.1 Add nullable normalized employee-number columns and non-null uniqueness constraints/indexes to the global user model and migration.
- [x] 1.2 Add canonical employee-number validation/normalization and safe account-summary mapping.

## 2. Registration and authentication

- [x] 2.1 Add registration DTOs, service port, repository transaction, password hashing, generic duplicate handling, and audit event.
- [x] 2.2 Update account authentication ports and service to resolve email or employee number with legacy email compatibility and unchanged generic failure/rate limiting behavior.
- [x] 2.3 Add `POST /api/v1/account/register`, wire the service through application state, and ensure registration cannot grant roles, memberships, sessions, or tenant access.
- [x] 2.4 Extend account context and login responses with employee number and update account-session behavior documentation.

## 3. Contract and security tests

- [x] 3.1 Update OpenAPI, error catalog, Chinese documentation metadata, and contract validation for registration and identifier login.
- [x] 3.2 Add unit and HTTP tests for valid registration, duplicate email/employee number, both login identifiers, conflicting legacy input, rate limiting, generic errors, and no privilege escalation.
- [ ] 3.3 Add migration and full contract/type/format checks, then verify Swagger and frontend handoff documentation.
