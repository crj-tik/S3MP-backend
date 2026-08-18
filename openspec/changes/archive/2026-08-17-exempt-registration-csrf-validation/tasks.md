## 1. Backend CSRF boundary

- [x] 1.1 Add the exact `/api/v1/account/register` path to the backend browser CSRF exemption set.
- [x] 1.2 Verify that the exemption is exact-path only and does not cover other `/api/v1/account/` mutations.

## 2. Regression coverage

- [x] 2.1 Add an HTTP test proving registration succeeds without session cookies or an `X-S3MP-CSRF` header.
- [x] 2.2 Add an HTTP test proving registration with stale account or tenant session cookies is not rejected by CSRF validation.
- [x] 2.3 Add or retain tests proving authenticated unsafe endpoints still reject missing or mismatched CSRF proof.

## 3. Contract and verification

- [x] 3.1 Confirm OpenAPI and frontend documentation describe registration as a public endpoint that does not require an existing CSRF token.
- [x] 3.2 Run focused browser-account authentication tests and contract validation.
- [x] 3.3 Run the relevant full test subset and record any unrelated environment failures separately.
