## Context

The identity management API currently lists users through an inner join to active Membership rows, so it cannot discover globally registered users who are absent from the current tenant. User accounts are global, while Membership rows are tenant-scoped and unique per tenant/user pair.

## Goals / Non-Goals

**Goals:**

- Add a tenant-scoped candidate search with the existing membership-management authorization boundary.
- Query global active accounts while excluding every current-tenant Membership state.
- Support one normalized fuzzy query over email, display name, and employee number, with empty-query directory behavior.
- Keep response fields deliberately limited to safe identity data and use bounded deterministic pagination.

**Non-Goals:**

- No invitation creation or membership mutation in this endpoint.
- No cross-tenant membership details, roles, permissions, or account status fields in the response.
- No search across disabled or deleted global accounts.

## Decisions

- **Dedicated candidate query:** Add a repository method that selects `UserModel` and applies a correlated `NOT EXISTS` against `MembershipModel` for the current tenant. A left join could work, but `NOT EXISTS` makes the all-status exclusion explicit and avoids duplicate rows.
- **Permission boundary:** Bind the route to `members.manage`, matching the existing create/update membership operations and the administrator use case. `members.read` alone cannot invite users.
- **Matching semantics:** Trim and case-fold the query; use case-insensitive containment against normalized email, display name, and normalized employee number. Empty input omits the match predicate.
- **Pagination:** Reuse the existing opaque cursor pattern bound to tenant, principal, authorization version, and normalized query. Order by `UserModel.id` and cap the page at the existing management default (50).
- **Response shape:** Add a strict `MemberCandidateResponse` and page wrapper with `items` and `next_cursor`; do not reuse `UserResponse` because candidate responses intentionally omit status and timestamps.

## Risks / Trade-offs

- [Risk] Fuzzy matching over display names can require a broad scan → retain a bounded page and rely on normalized indexed email/employee fields for exact prefixes where available.
- [Risk] A removed membership may be mistaken for an available candidate → exclude by existence of any membership row, not by membership status.
- [Risk] Cursor reuse with a changed query could mix results → include the normalized query in cursor encoding and validation.

## Migration Plan

Add the route, permission classification, schema, and repository query in one release. No database migration is required. Existing member-management endpoints remain unchanged. Rollback removes the endpoint and contract entry without altering account or membership data.
