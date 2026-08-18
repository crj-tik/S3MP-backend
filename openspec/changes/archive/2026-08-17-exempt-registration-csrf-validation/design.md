## Context

The registration route is `/api/v1/account/register` and is already public in
the authentication middleware. The frontend deliberately omits
`X-S3MP-CSRF` for this route because a new visitor has no session CSRF cookie.
The browser CSRF middleware currently exempts only `/api/v1/auth/login`; if an
old account or tenant session cookie remains in the browser, it therefore
tries to validate a token on registration and returns 403.

## Goals / Non-Goals

**Goals:**

- Make the backend CSRF exemption set match the public authentication routes.
- Preserve CSRF enforcement for every authenticated unsafe request.
- Add regression coverage for registration with and without stale session cookies.
- Keep the frontend and OpenAPI behavior explicit and consistent.

**Non-Goals:**

- Do not change password validation, account uniqueness, rate limiting, or registration authorization.
- Do not exempt any tenant, platform, logout, or tenant-session mutation.
- Do not introduce a new CSRF token endpoint or change cookie names.

## Decisions

1. **Exempt the exact registration path.** Add `/api/v1/account/register` to the
   backend's exact CSRF exemption set. This is preferable to a broad prefix
   exemption because other `/api/v1/account/` routes must remain protected.

2. **Keep authentication and CSRF public-path definitions aligned.** The
   registration path is already public to credential resolution; the CSRF
   middleware must make the same route-level decision. The frontend already
   treats login and registration as the two pre-session mutations.

3. **Test stale-cookie behavior explicitly.** A request with either session
   cookie must still reach registration without a CSRF header, while an unsafe
   authenticated endpoint must continue to return `csrf_validation_failed`
   without a valid header. This prevents the fix from accidentally disabling
   the broader browser security boundary.

## Risks / Trade-offs

- **[Risk]** A logged-in browser can submit a registration request without CSRF proof. → **Mitigation:** registration creates a new account from explicitly supplied fields and does not mutate the existing account or tenant session; all existing-session mutations remain protected. Add a test to preserve this exact boundary.
- **[Risk]** Future public authentication routes may again be added to only one middleware's allowlist. → **Mitigation:** keep route constants and regression tests explicit, and document the two public exceptions.

## Migration Plan

No database or cookie migration is required. Deploy the middleware change and
restart the API process so the route allowlist is loaded. Rollback consists of
reverting the allowlist entry; this restores the current, but defective,
behavior.
