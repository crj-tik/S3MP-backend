## Why

Accounts can be invited to tenants, but the browser API does not currently let an authenticated user accept an invitation or discover invited memberships alongside active tenants. This prevents the frontend from completing tenant onboarding and forces it to rely on incomplete account context.

## What Changes

- Add an authenticated account endpoint to accept a tenant invitation by `membership_id`.
- Transition only the caller's `Membership` from `invited` to `active` after a successful acceptance.
- Extend `GET /api/v1/auth/me` tenant entries to include `membership_id` and preserve `membership_status`, returning both active and invited memberships.
- Return the updated account context from the acceptance endpoint (with frontend re-fetch remaining supported).
- Reject unknown, foreign, already-active, expired, or otherwise invalid memberships without changing state.

## Capabilities

### New Capabilities

- `tenant-invitation-acceptance`: Authenticated acceptance of invited tenant memberships and the resulting status transition.

### Modified Capabilities

- `browser-account-authentication`: Account context and tenant-selection behavior now expose membership identifiers/statuses and include invited memberships while tenant sessions remain restricted to active memberships.

## Impact

- Authentication/account-context routes and response schemas under `/api/v1/auth`.
- Membership lookup and status transition persistence in the tenant/account service layer.
- API tests, OpenAPI/API documentation, and frontend-facing account context contracts.
