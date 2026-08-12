## Why

The archived file-security change introduced useful components, but the production request path still bypasses them: session cookies are not converted to their stored digest, several file and multipart operations authorize only by tenant, and ingestion provenance is never persisted. This leaves broken authentication and authorization bypasses in the local MinIO/PostgreSQL deployment, so the behavior must be converged before further file features are added.

## What Changes

- Make session-cookie authentication use the same one-way token-digest algorithm as persisted sessions, and model API-key callers as application principals rather than memberships.
- Route every file, upload, download-signing, multipart, delete, and object-operation command through one authorization-and-canonical-key boundary using the authenticated principal, storage-space scope, and current authorization version.
- Make presigned GET and upload/multipart object keys derive from an authorized relative key and storage-space root prefix; never sign a caller-supplied physical bucket key.
- Implement the MinIO multipart lifecycle and provider metadata verification needed to verify completion before a file becomes available.
- Persist ingestion intent, authorization evidence, provider verification, idempotency outcome, and terminal events transactionally with file state; repair invalid foreign-key delete behavior.
- Honor `Idempotency-Key` and `If-Match` on the contract routes, and add end-to-end regression coverage for the previously bypassable paths.

## Capabilities

### New Capabilities

- `file-ingestion-provenance`: Durable, immutable-enough ingestion lifecycle records and events that connect an authorized upload or multipart session to verified object metadata and file availability.

### Modified Capabilities

- `backend-file-storage`: Require all file paths to authorize a canonical relative key, securely derive physical keys, verify object-provider state, and execute a real multipart lifecycle.
- `backend-identity-authorization`: Require credentials to resolve to correctly typed, current principals and invalidate stale or unusable session authorization.
- `backend-api-contract`: Require mutation concurrency headers and secure authorization failures to be enforced consistently by the published file API.

## Impact

- Affected code: authentication middleware, identity provider/session persistence adapter, file router/application service/repositories, storage adapters, SQLAlchemy models, Alembic migrations, API contract, and integration tests.
- Systems: PostgreSQL persists session and ingestion state; MinIO is the verified object provider. Redis remains a cache/coordination aid and must not be an authorization source of truth.
- **BREAKING**: callers may no longer use raw physical S3 keys for download signing; all requests must be authorized against a storage-space-relative canonical key. Existing clients that omit required concurrency headers on protected mutations will receive a stable validation/precondition error.
