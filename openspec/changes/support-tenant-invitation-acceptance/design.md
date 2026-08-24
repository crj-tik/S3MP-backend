## Context

The existing browser account session already resolves memberships for `/api/v1/auth/me` and restricts tenant-session creation to active memberships. The change adds a state transition on the account security domain while keeping tenant-session selection unchanged.

## Goals / Non-Goals

**Goals:**

- Reuse the existing authenticated account context and CSRF middleware.
- Load the membership by both `membership_id` and authenticated account id to enforce ownership without leaking foreign memberships.
- Perform an atomic invited-to-active transition and build the same normalized AccountContext returned by `/api/v1/auth/me`.
- Include active and invited memberships in `/auth/me`, with stable membership identifiers and statuses.

**Non-Goals:**

- No invitation email/token issuance or revocation workflow.
- No automatic tenant-session creation after acceptance.
- No changes to permissions, roles, quotas, or tenant-scoped authorization.

## Decisions

- **Account-scoped endpoint:** Add the route beside account auth routes and protect it with account authentication plus account CSRF. This matches logout and other account mutations; using tenant CSRF would be incorrect before a tenant session exists.
- **Ownership-first lookup:** Query membership constrained to the current account (and tenant relation) so foreign IDs resolve to the same not-found/invalid response rather than revealing existence.
- **Status transition:** Accept only `invited` memberships that pass the model's existing validity/expiry rules. Use a conditional update or transaction lock to make concurrent acceptance idempotent and prevent partial context updates.
- **Shared serializer:** Extend the existing tenant/account context serializer rather than introduce a second response shape. Both `/auth/me` and acceptance return `membership_id` and `membership_status` for active and invited entries.
- **Tenant session remains active-only:** Keep the existing selection guard; an invited membership appearing in account context is informational until accepted.

## Risks / Trade-offs

- [Risk] Concurrent acceptance requests may race → use a conditional status update/row lock and return the post-commit context.
- [Risk] Existing clients may assume only active tenants are returned → preserve `membership_status` and ensure tenant selection still rejects invited entries.
- [Risk] Error semantics could leak membership ownership → normalize foreign/missing/ineligible cases to the established account-auth invalid-membership response.

## Migration Plan

Deploy the route and serializer changes together. Existing clients continue to receive the prior tenant fields plus `membership_id`/`membership_status`; clients that cannot accept invitations can ignore invited entries. Rollback removes the route behavior while leaving already accepted memberships active, so rollback is not state-reversing.
