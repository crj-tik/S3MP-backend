## Context

See proposal.md for the motivation. The current API Key authenticates a target application and the application data plane derives the target namespace from that Key. `application_code` already represents the same-tenant application that performed the action for audit, while browser routes select their target by `application_id`. File APIs currently accept application-relative paths, so a directory-limited Key would otherwise be able to address a sibling directory in its target application.

Object stores use key prefixes rather than native directories. The platform already derives the tenant/application namespace server-side and validates canonical relative paths.

## Goals / Non-Goals

**Goals:**

- Persist a canonical optional prefix on each API Key and expose a non-secret summary in management responses.
- Make application API paths relative to that prefix and enforce the resulting complete application-relative path throughout the entire file lifecycle.
- Preserve the separate target-application and audit-actor semantics introduced for `application_code`.
- Make a newly configured empty directory observable without exposing technical marker objects as files.

**Non-Goals:**

- Changing browser application-ID routes or introducing API Key credentials for browser management endpoints.
- Adding cross-tenant access, application-to-application grants, or path patterns/wildcards.
- Letting callers override an existing Key's directory range; changing a range requires issuing a new Key.

## Decisions

### Store one canonical application-relative directory prefix on the Key

Add an optional nullable `directory_prefix` field to the API Key aggregate and persistence model. `NULL` denotes the target application's root; a non-null value is a canonical relative directory without a trailing slash. The issue request and API Key management UI use the same canonical-directory validator as file keys, except that the root is represented by omission rather than an empty submitted path.

This is preferable to storing a physical S3 prefix because physical keys embed tenant and application identifiers, making the policy harder to validate and more vulnerable to namespace confusion. It is also preferable to a separate directory ACL because this change narrows one credential rather than changing the application's permissions.

### Treat application API file paths as Key-relative

For application API routes, normalize the caller's object key or list prefix as a relative path beneath the authenticated Key's `directory_prefix`. The server composes:

```text
full_application_relative_key = directory_prefix + "/" + key_relative_to_key
physical_key = tenant_namespace + "/" + target_application_id + "/" + full_application_relative_key
```

When the scope is root, composition uses the supplied key unchanged. List prefix omission means the Key root; an explicit prefix is resolved below it. The path resolver validates both inputs and applies directory-boundary checks; raw concatenation and client-provided application-root paths are never trusted.

This avoids information leakage and probing of sibling paths. Retaining application-root-relative request keys and merely rejecting strings outside the prefix was rejected because it exposes the hidden directory structure and makes clients responsible for a server-owned boundary.

### Establish a logical directory at Key issuance

The database Key range is authoritative. When a non-root range is issued, create a conventional zero-byte folder marker only if the existing folder-browsing implementation needs an object to show an empty folder; all file lists and quota accounting must filter that marker. If the storage adapter and UI already model directories from persisted prefixes, store only the prefix record and do not create a provider object.

This preserves the user's requested directory-creation behavior while recognizing that S3-compatible storage has no independent folder entity. Failure to establish the configured logical directory causes key issuance to fail atomically or compensates by removing the newly issued Key.

### Persist scope evidence for durable file work

At creation, upload sessions, multipart sessions, pre-sign intents, file operations and asynchronous ingestion evidence record the API Key ID, its canonical directory prefix, complete application-relative key and target application. Follow-up endpoints load those records and revalidate that the stored complete key remains inside the recorded prefix, then revalidate the Key and target application state.

The stored evidence, rather than any follow-up request path, drives direct-upload completion and multipart completion. This prevents a valid session identifier from being used as a directory-boundary escape.

### Keep actor application code separate

The authenticated Key selects `target_application_id` and `directory_prefix`; `application_code` selects `actor_application_id` only after the same-tenant active check. Audit records carry both identities. The actor code does not alter the path resolver, authorization target, Key scope or Key directory prefix.

## Risks / Trade-offs

- [A marker object appears as a user file or consumes quota] → use a reserved marker convention, filter it at every user-visible list endpoint and exclude it from quota/file records; prefer the persisted logical-directory representation when available.
- [Old application clients send application-root-relative keys] → publish a breaking application API contract, update examples and return a clear validation/permission failure rather than silently interpreting an out-of-range full path.
- [Continuation routes omit the actor code or scope check] → centralize Key-scope resolution in request context and add route-matrix tests for create, read, list, direct upload, multipart, delete and object operations.
- [Key scope is changed after a URL is signed] → Key issuance scope is immutable; revocation blocks new platform calls and normal pre-signed URL expiration remains the documented exposure window.

## Migration Plan

1. Add the nullable directory-prefix schema field, DTO/OpenAPI fields and canonical-path validation. Existing Keys are backfilled as root-scoped.
2. Add prefix-aware request context and durable evidence fields, then enforce them before any provider access across every application API data-plane route.
3. Update the API Key issue/detail UI to collect and show the optional directory. Generate frontend client types from the updated contract.
4. Deploy with root scope as the backward-compatible default; issue new directory-limited Keys for restricted integrations.
5. Validate root and child scopes, sibling-prefix rejection, direct/multipart continuation, revoked Key behavior, target/actor audit attribution and browser route independence. Roll back by disabling the new UI field and treating null/backfilled Keys as root scopes; do not remove persisted prefixes during rollback.
