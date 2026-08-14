## Context

The existing `user_account` is global, but principals, memberships, roles,
RoleBindings, and browser sessions are tenant-scoped. The runtime can resolve an
existing tenant session but has no login/session issuance HTTP boundary. See
proposal.md for the motivation and the delta specs for observable requirements.

## Goals / Non-Goals

**Goals:**

- Preserve tenant isolation while adding a platform control plane.
- Establish browser sessions securely in both local development and production.
- Make bootstrap, tenant creation, support access, and privilege changes auditable.

**Non-Goals:**

- Do not add self-service public registration, external OAuth, MFA, or SCIM in
  this change.
- Do not grant platform administrators implicit access to tenant file content,
  application API Keys, or tenant management endpoints.
- Do not replace the existing tenant Role/RoleBinding authorization evaluator.

## Decisions

### 1. Model platform authorization outside the tenant model

Add `platform_role` and `platform_role_binding` keyed to `user_account`, with
immutable built-in roles such as `platform_admin`, `platform_operator`, and
`platform_auditor`. Platform permissions live in a separate catalog and are
evaluated by a separate dependency. This prevents null-tenant or synthetic
tenant-principal escape hatches.

Alternative: reuse `role` with a nullable tenant ID. Rejected because existing
foreign keys, evaluators, and safety assumptions all require tenant scope.

### 2. Use account sessions before tenant sessions

Add `account_session` for login state. `POST /auth/login` verifies a global user
credential and creates it; `GET /auth/me` returns account/platform context and
accessible tenant summaries. `POST /auth/tenant-sessions` requires an account
session and creates the existing tenant-bound `auth_session` for one active
membership. Tenant endpoints continue accepting only the tenant session.

Alternative: put a nullable tenant ID on `auth_session`. Rejected because it
would blur the security invariant that a tenant session always names a valid
membership and principal.

### 3. Keep bootstrap out of public HTTP

Provide a deployment command that hashes an interactively supplied password and
creates the first platform administrator in one transaction, only if none is
active. Record a platform audit event. Later platform role changes use protected
platform APIs.

Alternative: accept a first-admin secret at a public endpoint. Rejected because
it expands the remotely reachable attack surface and complicates secret rotation.

### 4. Create tenants atomically with the initial tenant administrator

The platform tenant-create service creates tenant, human principal, active
membership, immutable `tenant-admin` role (if absent), and its RoleBinding in
one transaction. The initial administrator must be an existing active account;
invitation workflows are a later capability.

### 5. Use explicit support-access grants

Support access is a time-bounded, separately auditable grant that materializes a
restricted tenant Membership/RoleBinding only after authorization and, where
required, approval. Default grants exclude file-content permissions. Revocation
and expiry advance authorization versions and revoke tenant sessions.

### 6. Cookie and CORS policy is environment-derived

Add configured exact browser origins. CORS allows credentials only for those
origins. Cookie policy is `Secure=true` outside development; development may use
`Secure=false` only when configured. Login writes an HttpOnly session cookie and
a readable CSRF cookie; unsafe browser requests require a matching header.

## Risks / Trade-offs

- [Two browser sessions can confuse clients] → Use distinct cookie names and
  expose account versus selected-tenant state explicitly.
- [Bootstrap command misuse] → Permit only zero-to-one active platform-admin
  transition, require interactive secret input, and audit every attempt.
- [Support access becomes a bypass] → Require reason, bounded expiry, audit in
  both planes, and no default file-content access.
- [Credentialed CORS misconfiguration leaks sessions] → Reject wildcard origins
  with credentials and reject insecure production cookie configuration.

## Migration Plan

1. Add tables, indexes, platform audit storage, session configuration, and
   additive tenant lifecycle fields.
2. Seed immutable platform roles and tenant-admin permissions idempotently.
3. Deploy bootstrap command; create and verify the first platform admin before
   exposing platform management APIs.
4. Deploy account login/logout/context and tenant-session selection, then update
   frontend configuration from mock to real mode.
5. Enable platform tenant lifecycle and support-access APIs after adversarial
   authorization, CORS, cookie, and cross-tenant tests pass.

Rollback retains additive tables and sessions. Disable login/platform routes and
revoke affected sessions if necessary; never transform a platform grant into an
implicit tenant bypass. Tenant data-plane access continues using existing tenant
sessions and authorization checks.

## Open Questions

- Whether support access requires mandatory two-person approval for every tenant
  or only tenants marked as regulated can be configured without changing the
  core model.
