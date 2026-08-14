## Why

The backend can validate an existing tenant session but cannot establish one, and
it has no platform-level control plane for bootstrap or tenant lifecycle
governance. Treating a platform operator as a tenant administrator would break
the tenant isolation guarantees already enforced for files and credentials.

## What Changes

- Add browser authentication that creates a global account session, supports
  logout and CSRF protection, and allows an authenticated human to explicitly
  select an active tenant membership for a tenant session.
- Add platform roles and platform role bindings separate from tenant principals,
  tenant roles, and tenant RoleBindings.
- Add a one-time, audited bootstrap flow for the first platform administrator.
- Add platform tenant lifecycle APIs that create a tenant atomically with its
  initial tenant administrator and cannot directly access tenant data-plane
  resources.
- Add development CORS and cookie-policy configuration while retaining secure
  production defaults.
- Add an explicit, audited, time-bounded support-access workflow rather than an
  implicit cross-tenant administrator bypass.

## Capabilities

### New Capabilities

- `platform-control-plane`: Platform-wide administrator roles, bootstrap,
  tenant lifecycle governance, and audited support access.
- `browser-account-authentication`: Global account login, logout, CSRF-protected
  sessions, and explicit tenant-session selection.

### Modified Capabilities

- `backend-identity-authorization`: Separate global account authentication from
  tenant membership authorization and session resolution.
- `backend-api-contract`: Publish the authentication and platform control-plane
  HTTP contract.
- `local-infrastructure-runtime`: Configure development browser origins and
  non-secure local cookies without weakening production policy.

## Impact

Affected areas include OpenAPI and permission catalogs, FastAPI middleware and
routers, identity/session persistence, tenant persistence, audit records,
bootstrap tooling, local configuration, CORS, and frontend integration. Existing
tenant RoleBindings, application API Keys, and file authorization remain
tenant-scoped and must not acquire platform bypass behavior.
