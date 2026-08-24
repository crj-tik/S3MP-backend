## Why

Tenant administrators currently need to know an existing user's exact email before creating a membership, and the existing user listing only returns users already visible through tenant memberships. A tenant-scoped candidate search will make invitations discoverable while preventing administrators from selecting users who already belong to the tenant.

## What Changes

- Add `GET /api/v1/member-candidates` for authorized tenant administrators.
- Support case-insensitive fuzzy matching across email, display name, and employee number through one `query` parameter.
- Return globally registered active users who have no Membership row in the current tenant, regardless of whether a query is supplied.
- Exclude every user already associated with the current tenant, including invited, active, suspended, and removed memberships.
- Return only safe user identity fields: `id`, `email`, and `display_name`.
- Apply a bounded result limit and consistent ordering suitable for an empty-query directory lookup.

## Capabilities

### New Capabilities

- `tenant-member-candidates`: Tenant-scoped candidate discovery for inviting globally registered users.

### Modified Capabilities

- `backend-api-contract`: Add the candidate-search operation, response schema, permission classification, and query contract to the public API documentation.

## Impact

- Identity API router, management service, and SQL identity repository.
- Tenant membership authorization and permission mapping (`members.manage`).
- OpenAPI/error/contract documentation and identity HTTP/repository tests.
