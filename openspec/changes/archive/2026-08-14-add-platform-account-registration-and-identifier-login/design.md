## Context

`user_account` is already the global identity table used by account sessions, tenant memberships, and platform role bindings. It currently has unique normalized email and optional password hash, but no employee-number identity or public registration route. The existing account authentication service is email-specific and the platform repository already contains bootstrap-only user creation logic.

## Decisions

### 1. Keep one global account table

Add `employee_number` and `normalized_employee_number` to `user_account`; do not create a second account table. Use a nullable normalized column so existing accounts survive the migration and can be completed later.

### 2. Normalize identities deterministically

Trim and case-fold email. Trim and case-fold the employee number as well, while validating a documented company-number character set and length. Enforce unique indexes on normalized email and non-null normalized employee number. Registration must handle database uniqueness races and map them to one generic duplicate-account error.

### 3. Introduce a dedicated registration service

Create an application service that validates input, hashes the password with the existing `PasswordHasher`, persists the user in one transaction, writes an audit event, and returns a safe account summary. It must not call tenant or platform-role creation code.

### 4. Make login identifier-aware

Change the authentication port from email-only lookup to identifier lookup. The service classifies an identifier as email when it has the documented email form; otherwise it looks up the normalized employee number. If a transitional request supplies both canonical `identifier` and legacy `email`, they must resolve to the same account or be rejected. Preserve generic failure responses and rate limiting keyed by a privacy-safe normalized identifier.

### 5. Protect public registration

Registration is public but rate-limited and must not reveal whether an email or employee number already exists. It creates no account session. Existing browser CSRF rules continue to apply according to the account-session policy; no API key or tenant session is accepted as a registration prerequisite.

### 6. Contract and migration safety

Add a migration with nullable employee-number columns and unique non-null indexes, update DTOs and OpenAPI metadata, and add tests for registration, duplicate races, both login paths, generic failures, no privilege escalation, migration compatibility, and contract synchronization. The old email login field is marked deprecated and retained only for the agreed frontend transition window.

## Flow

```text
Register: validate → normalize → hash → insert global user → audit → safe summary
Login: identifier → classify email/employee number → rate limit → verify hash → account session
Tenant access: account session → select tenant → tenant session → tenant APIs
```

## Non-Goals

- No public self-service platform-admin role assignment.
- No automatic tenant creation or membership on registration.
- No password reset, email verification, MFA, or employee-directory synchronization in this change; these should be separate changes.
