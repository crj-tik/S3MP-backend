## Context

See [proposal.md](proposal.md) for the motivation. The archived change added an identity provider, `AuthorizedFileCommand`, ingestion models, and a MinIO adapter, but the runtime path still calls legacy file-service methods that accept only `tenant_id`. Consequently, authorization evidence is not produced, session cookies are queried as raw strings although storage uses a digest, multipart is database-only, and ingestion records are never written.

PostgreSQL is the durable authority for identities, file state, idempotency, and provenance. MinIO at the configured local S3 endpoint is the authority for object existence and object metadata. Redis may cache only values that are safe to invalidate by `authorization_version`; it cannot authorize an operation by itself.

## Goals / Non-Goals

**Goals:**

- Establish one request-to-object path in which credentials become a typed principal, authorization produces a canonical command, and only that command can reach PostgreSQL or MinIO.
- Make single-part and multipart ingestion durable, idempotent, provider-verified, and auditable before a file is visible.
- Close known same-tenant authorization bypasses and raw-key signing paths without changing the public API surface beyond the documented secure key/precondition semantics.
- Make every completion outcome recoverable: committed, failed, quarantined, aborted, or partial failure is persisted rather than inferred from an HTTP response.

**Non-Goals:**

- Building malware scanning, content extraction, end-user sharing links, cross-region replication, or a generic S3 proxy.
- Retrofitting historical files into provenance records except through a separately approved maintenance migration.
- Making Redis, presigned URLs, or client supplied metadata a source of truth for authorization or object completion.

## Decisions

### 1. Resolve credentials before routing and keep principal types explicit

The authentication middleware will transform the `s3mp_session` cookie using the same HMAC/SHA-256 (or existing centralized digest helper) used when issuing and persisting sessions, then call the session store with `bytes`. It will never log or persist the raw cookie. Session resolution will validate revocation, expiry, principal, membership, and the current authorization version before yielding a human `PrincipalContext`.

API-key authentication will resolve an explicit application subject context, e.g. `subject_kind=application`, `principal_id=application_id`, and no synthetic membership ID. The evaluator's binding lookup will branch by subject kind: human contexts resolve direct/group/membership bindings; application contexts resolve application bindings. This is preferable to reusing a membership UUID because the latter gives application callers accidental human semantics and makes audit evidence ambiguous.

Authorization-version comparison will reject credentials that predate the current applicable membership/application version rather than merely returning `max(...)`. A version bump therefore invalidates old credential-derived decisions. Redis cache entries, if retained, must include tenant, principal, subject kind, canonical action/key and authorization version; mismatch is a cache miss.

### 2. Make AuthorizedFileCommand the only bridge from request intent to storage work

Introduce a command factory/service invoked by every file route. It receives `PrincipalContext`, storage-space identity, action, relative key(s), canonical request semantics, request ID, and idempotency key. It will:

1. resolve the tenant-owned storage space;
2. canonicalize each relative key and reject invalid values;
3. load applicable bindings and evaluate default-deny authorization;
4. derive `physical_key = normalized(root_prefix) + '/' + relative_key` exactly once;
5. calculate a canonical request fingerprint from tenant, typed principal, action, space ID, keys, content length/type/checksum, conditional version, and normalized operation payload; and
6. return immutable authorization evidence for persistence and auditing.

File services and repositories will accept the command (or a narrower command-derived value object) rather than a bare tenant ID for all externally initiated operations. This includes list, read metadata, create/complete/proxy upload, download signing, multipart create/get/part/complete/abort, delete, and copy/move. Ownership checks supplement, but never replace, role-binding authorization.

The alternative of adding a guard to each legacy method is rejected because it would leave different key canonicalization, authorization evidence, and physical-key derivation paths that can drift.

### 3. Treat upload and multipart completion as provider-verified state transitions

For a single upload, initiation persists a pending upload session and `initiated` ingestion record before giving the caller a content path. Completion loads the original authorized command and verifies `HeadObject` against its physical key, exact content length, expected content type normalization, required checksum, ETag and version ID when provider support is configured. Only then does one database transaction create/update the file object, settle quota, set upload/session and ingestion states to committed, and append the committed event.

The MinIO port will expose explicit capabilities and operations: create multipart upload, presign/upload a part if supported by the contract, list parts, complete multipart upload, abort multipart upload, head object, and delete/quarantine. Service code must reject any requested capability that the adapter declares unsupported; it must not simulate completion from database part rows. The provider upload ID and part ETags are persisted and compared at completion. Expired or failed sessions are aborted best-effort and recorded as terminal; retry cleanup remains possible.

On provider verification failure, database file availability is never committed. The record is marked `failed` or `quarantined`, an event is appended, and cleanup is queued or attempted using the derived physical key only. This favors an explicit recoverable state over deleting evidence or falsely reporting success.

### 4. Use a durable ingestion aggregate and transactional outbox-style event write

`file_ingestion_record` is the root lifecycle row. It records authorized intent, provider facts, idempotency identity/fingerprint, creator and acting principal, and status. `file_ingestion_event` is append-only and stores minimal non-secret transition evidence. A repository will implement:

- `begin_or_replay(command)`: atomically insert/retrieve by `(tenant_id, idempotency_fingerprint)` and reject a reused key whose canonical request hash differs;
- `record_provider_result(...)`: persist provider metadata and a transition event;
- `commit_verified_file(...)`: in one transaction, conditionally transition the ingestion row, update file/session/quota state, write audit/outbox data, and return the stable result;
- `fail_or_quarantine(...)`: conditionally record terminal failure and event without exposing physical-key details in public errors.

The migration will replace invalid composite foreign keys that use `ON DELETE SET NULL` while including non-null `tenant_id`. Provenance retention is chosen explicitly: retain terminal records/events, set only nullable foreign reference IDs to NULL through separate single-column references or use `RESTRICT`/soft deletion; never null tenant scope. The unique idempotency constraint applies only when an idempotency key is supplied, and a separate canonical request hash makes conflicting reuse detectable.

An external MinIO operation cannot be part of a PostgreSQL transaction. Intent is committed before the object call; verified result and terminal outcome are committed afterward. Crashes leave a discoverable pending record that reconciliation can inspect. This is safer than pretending to have a distributed transaction.

### 5. Enforce preconditions at the application boundary

Routes pass `Idempotency-Key` and `If-Match` into commands; they must no longer discard parsed headers. A missing required idempotency key is rejected before any provider call. `If-Match` is evaluated against the current file version/ETag within the mutation transaction; mismatch returns `412 precondition_failed` (or the registered catalog equivalent) and performs no object delete/update. Equivalent idempotent retries return the original response; conflicting reuse returns a stable `409 idempotency_conflict`.

Presigned download requests contain `space_id` and a relative key/file reference. The service resolves and authorizes it, confirms the file's tenant/space record and provider visibility, then signs the derived physical key. It never forwards a caller-supplied physical key to `presign_get`, and neither audit nor response persistence retains the full signed URL.

## Risks / Trade-offs

- [Changing `PrincipalContext` can touch many consumers] → add a backward-compatible typed subject field with explicit constructors, update all consumers in one change, and use type checks/tests to prevent synthetic memberships.
- [MinIO and AWS S3 metadata/checksum behavior differs] → define adapter capabilities, normalize supported metadata, and return a registered unsupported/verification error instead of silently weakening validation.
- [Object call succeeds but PostgreSQL commit fails] → leave the durable initiated record and reconciliation metadata; do not expose success, retry commit after re-verifying provider state.
- [Stricter authorization may expose missing RoleBindings in local test data] → seed explicit bindings in fixtures and provide clear `permission_denied` errors; do not introduce tenant-wide fallback access.
- [New idempotency keys can impact existing clients] → update OpenAPI/examples and return a stable validation error; retain read-only operations unchanged.

## Migration Plan

1. Add the centralized session digest helper and typed principal support with tests before enabling strict middleware behavior.
2. Add a follow-up Alembic revision that repairs ingestion foreign keys/indexes and creates any request-hash/provider fields; migrate empty development data normally. Production rollout must back up the database and validate the revision on a copy first.
3. Deploy command/repository and MinIO adapter support behind the existing file routes, then update contract fixtures and integration tests.
4. Run reconciliation for lingering `initiated` records: re-head the derived key, commit only verified objects, otherwise fail/quarantine and clean up according to policy.
5. Roll back application code by disabling new route behavior only before applying the schema migration. After migration, rollback remains forward-compatible because added provenance fields are retained; do not downgrade while terminal ingestion records exist without an explicit data-retention procedure.
