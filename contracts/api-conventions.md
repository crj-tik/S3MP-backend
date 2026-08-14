# S3MP API conventions

## Scope and versioning

- The public REST API is rooted at `/api/v1`. A breaking change requires a new major path.
- `contracts/openapi.yaml` is the normative HTTP contract. Unknown request fields are rejected unless a schema explicitly allows them.
- JSON property names, query parameters and enum values use `snake_case`. IDs are opaque strings and MUST NOT be parsed for tenancy or type.
- Clients send `Accept: application/json`; JSON requests send `Content-Type: application/json`.

## Authentication and tenancy

- `POST /api/v1/account/register` creates a global account with an email, company employee number, display name and password. Registration creates no tenant membership, platform role, session or API key.
- `POST /api/v1/auth/login` accepts the canonical `identifier` field, containing either an email or employee number. The legacy `email` field is retained temporarily for existing clients. Login creates only the account session; tenant data access still requires explicit tenant selection.
- Browser login creates a global `s3mp_account_session` HttpOnly cookie and a readable `s3mp_account_csrf` cookie. It authorizes only `/api/v1/auth/*` and `/api/v1/platform/*`; it never authorizes a tenant data-plane operation.
- `POST /api/v1/auth/tenant-sessions` explicitly selects an active tenant Membership and creates the separate `s3mp_session` HttpOnly cookie and readable `s3mp_csrf` cookie used by tenant APIs. Switching tenants requires selecting again.
- Unsafe requests authenticated by either browser session require the matching `X-S3MP-CSRF` header. Login is the only browser-authentication mutation exempt from this requirement.
- Applications use `Authorization: S3MP-Key <key_id>.<secret>`. The secret is returned only once when a key is created or rotated.
- The server derives the principal and tenant from credentials. A client-supplied resource ID never selects or overrides tenant context.
- Cross-tenant and unauthorized resource lookups return the same `404 resource_not_found` response where disclosure would reveal existence.

## Requests, idempotency and concurrency

- Mutating operations marked by OpenAPI accept `Idempotency-Key`, an opaque 8–128 character value. Its scope includes tenant, principal, method, route and request fingerprint. Reusing a key with different input returns `409 idempotency_key_reused`.
- Mutable resources expose an `etag`. Updates and destructive operations require `If-Match`; stale values return `412 etag_mismatch`.
- Bulk and state-machine operations return an operation resource. `partial_failure` means at least one step failed and the response MUST NOT be treated as complete success.

## Time and expiry

- All timestamps are UTC RFC 3339 strings with a `Z` suffix, for example `2026-08-10T09:30:00Z`.
- Durations in requests are integer seconds and use a `_seconds` suffix.
- Expiry is exclusive: a credential, binding, URL or upload is invalid at `expires_at`. Expired state produces `410` when the resource was known but can no longer be used.

## Pagination and filtering

- Collection responses use `{items, next_cursor}`. `next_cursor` is `null` when no further page exists.
- `cursor` is opaque, integrity-protected and bound to tenant, principal, authorization version, filters and sort order. Clients MUST NOT inspect, alter or reuse it with different query parameters.
- `limit` defaults to 50 and is at most 200. A changed or expired cursor returns `400 invalid_cursor`; authorization changes may also invalidate cursors.
- Collections have deterministic server-defined ordering documented per operation, normally newest first with ID as tie-breaker.

## Errors

All non-2xx JSON errors use this envelope:

```json
{
  "code": "permission_denied",
  "message": "The principal is not allowed to perform this action.",
  "request_id": "req_01J5YQ2NA8R6QJ8VY6X4Z6AT2M",
  "details": {"permission": "files.read"}
}
```

- `code` is stable and listed in `error-codes.yaml`; clients branch on it, never on `message`.
- `message` is safe for an end user and may change or be localized. `details` is optional, non-secret, code-specific structured data.
- Every response carries `X-Request-ID`; an accepted client `X-Request-ID` may be echoed after validation.
- Validation details identify fields using JSON Pointer. Secrets, S3 credentials and complete presigned URLs never appear in errors, logs or audit data.

## Authorization semantics

- Permission names come from `permission-catalog.yaml`. File permissions require a `storage_space` scope and may include a canonical prefix.
- Canonical prefixes are slash-delimited relative object prefixes: no leading slash, `.`/`..`, backslash, control character, empty segment or ambiguous encoding. The empty string means the whole storage space.
- Effective access merges matching allows, applies explicit deny before allow, and defaults to deny. Explanations contain stable reason codes and source references.
- Membership suspension, binding expiry and policy/group changes advance `authorization_version`; sessions, cursors and queued work are revalidated.

## Files, upload and presigning

- Object keys use the same canonicalization rules as prefixes and are authorized exactly as executed against S3.
- Upload initiation reserves quota. Completion verifies the actual object through storage metadata before it becomes `available`.
- Presigned URLs are short-lived and exact to method, key and signed headers. They are returned only in creation responses and never persisted or audited in full.
- Revoking a key prevents new requests and new signatures but cannot guarantee revocation of an already-issued URL before `expires_at`.
- Multipart sessions are bound to tenant, principal, space, canonical key, declared size and expiry. Part ETags are opaque and are not assumed to be MD5 values.

## Compatibility

- Additive optional properties and new endpoints are backward compatible. Clients MUST ignore unknown response fields.
- Removing/renaming fields, narrowing accepted values, changing status codes or changing permission/error semantics is breaking.
- Enum additions are potentially disruptive; generated clients should retain an unknown fallback.
