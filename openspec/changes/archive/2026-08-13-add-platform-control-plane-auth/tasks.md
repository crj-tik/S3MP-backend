## 1. Platform authority foundation

- [x] 1.1 Add additive migrations and models for platform roles, platform role bindings, platform audit events, account sessions, tenant lifecycle status, and supporting indexes/constraints.
- [x] 1.2 Seed immutable platform roles and the tenant-admin role/permission baseline idempotently without adding platform grants to tenant RoleBindings.
- [x] 1.3 Implement platform authorization evaluation and dependencies that accept only an account session and deny tenant data-plane access by default.
- [x] 1.4 Implement the one-time interactive bootstrap command for the first platform administrator, including password hashing, no-secret output, and immutable audit evidence.

## 2. Browser account authentication

- [x] 2.1 Add account credential lookup, login rate limiting, account-session issuance/persistence, account context lookup, and logout/revocation services.
- [x] 2.2 Add `POST /api/v1/auth/login`, logout, and account-context endpoints with uniform credential failure, opaque HttpOnly cookies, and no raw token response.
- [x] 2.3 Add tenant-session selection and revocation endpoints that create the existing tenant session only from an active unexpired Membership.
- [x] 2.4 Extend authentication middleware to distinguish account-session, tenant-session, and API-Key contexts without treating an account session as tenant authorization.
- [x] 2.5 Add CSRF cookie/header validation for unsafe browser-authenticated requests and environment-derived cookie policies.

## 3. Platform tenant lifecycle and support access

- [x] 3.1 Implement platform tenant list/get/create/update services and routes with platform permissions and redacted audit records.
- [x] 3.2 Make tenant creation transactional with an existing active initial administrator, a tenant principal, active Membership, and tenant-admin RoleBinding.
- [x] 3.3 Implement platform role grant/revocation management with expiry, immutable built-ins, authorization-version invalidation, and audit evidence.
- [x] 3.4 Implement explicit time-bounded support-access request, approval, materialization, expiry, and revocation flow; exclude file-content permissions by default.

## 4. Browser runtime and contract integration

- [x] 4.1 Add all authentication and platform APIs, schemas, security schemes, permission catalogs, error codes, and examples to OpenAPI.
- [x] 4.2 Add configured CORS origin allowlists with credentials; reject wildcard credentialed origins and insecure production cookie configuration.
- [x] 4.3 Document frontend real-mode settings, account/tenant session flow, CSRF handling, local Vite proxy option, bootstrap operation, and production origin configuration.

## 5. Verification and rollout

- [x] 5.1 Add unit and repository tests for bootstrap uniqueness, platform/tenant separation, tenant-creation atomicity, role expiry, and support-access expiry.
- [x] 5.2 Add HTTP tests for login failure uniformity, cookie attributes by environment, logout, tenant selection denial, CSRF rejection, CORS preflight, and no tenant context from an account session.
- [x] 5.3 Add adversarial tests proving platform administrators cannot directly access tenant files, storage credentials, application API Keys, or cross-tenant management routes without explicit temporary support access.
- [x] 5.4 Run migration, contract, format, type, full test, and local PostgreSQL/Redis/MinIO readiness verification; document deployment and rollback evidence.
