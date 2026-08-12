## Context

See proposal.md for motivation. Review found that the prior implementation only added local scaffolding: the auth middleware has no production session-context provider, the API Key path overloads application identity as membership identity, file routes and repositories still use tenant-only lookup, the file authorization guard is not in the main path, and no ingestion provenance migration exists. The design must now converge the actual HTTP-to-storage path, not only introduce domain helpers or tests.

## Goals / Non-Goals

**Goals:**

- Derive every protected request identity from server-verified credentials.
- Enforce a single canonical resource identity for authorization, persistence, and MinIO calls.
- Make completed ingestion independently verifiable and recoverable after partial failure.
- Prevent replay, session takeover, forged multipart completion, and duplicate settlement.

**Non-Goals:**

- Build a new external identity provider or alter the existing role model.
- Guarantee exactly-once object-storage calls; durable idempotent outcomes are the target.
- Retroactively prove provenance for legacy files that have no server verification record.

## Decisions

### 1. Authenticate once, then pass an immutable server-derived context

Middleware resolves a session, API Key, or service credential and validates its tenant/principal/membership bindings and authorization version. App assembly MUST register a concrete identity-context provider backed by the production repository before middleware runs. It stores a request-scoped immutable context with subject kind, credential type, and a non-secret credential identifier/fingerprint. Public health and explicit login/callback routes are exempt; every other protected router uses the same dependency.

User-session contexts contain a real membership identifier. Application/API-Key contexts use an application/service subject kind and MUST NOT populate membership fields with an application identifier. Authorization lookup handles those subject kinds explicitly.

The production middleware MUST NOT accept a pre-populated `request.state.principal_context` bypass. Test context injection belongs in a test-only app factory or dependency override.

**Alternative considered:** router-specific identity extraction. Rejected because it enables inconsistent checks and makes security review route-by-route.

### 2. Authorize an `AuthorizedFileCommand` before all storage or persistence side effects

The command contains tenant, acting principal, storage space, bucket, canonical relative key, physical key, operation, authorization evidence, request ID, and idempotency fingerprint. The file authorization service resolves active direct/group bindings for the principal, filters by space and prefix, applies explicit deny before allow, and records evidence. The MinIO adapter accepts only a command-derived storage request.

`physical_key = canonical_join(space.root_prefix, relative_key)` is computed once after canonicalization. Client input is always relative and never replaces the root prefix.

**Alternative considered:** authorize a key then reconstruct a different S3 key inside the adapter. Rejected because it breaks the authorization/execution equivalence guarantee.

### 3. Bind workflow ownership to creator, with explicit delegation

Every file service method receives `PrincipalContext`, not a bare tenant identifier. Session and operation reads lock and compare the creator against the acting principal. A non-creator must pass the same action/space/key authorization flow and possess an explicit delegation-capable permission; the result records creator and actor. Tenant membership alone never grants workflow control.

This applies to upload read/content/completion, all multipart read/part/complete/abort operations, file-operation retrieval, file read/delete, presigned download, and recovery. Unauthorized resource lookups return a non-enumerating error and must not mutate provider or database state.

### 4. Use immutable ingestion provenance plus append-only lifecycle events

Add `file_ingestion_record` and `file_ingestion_event`. The record stores session/multipart links, actor and credential provenance, logical and physical storage identity, verified metadata (length, content type, ETag, checksum, provider version where available), authorization evidence hash, policy/authorization version, request/idempotency correlation, quota and audit links, and status. Events append each transition and error metadata. `file_object` remains the current available-file projection.

Terminal availability requires one database transaction that locks the session and quota, creates the immutable record/event, writes or updates the file projection, settles quota, writes redacted audit/outbox entries, and marks the session committed. The schema prevents duplicate committed records for a session and duplicate effects for a tenant-scoped idempotency key/provider object identity.

The migration adds foreign keys from provenance to upload/multipart session, file projection, quota reservation and audit event where applicable; unique constraints for committed session/provider identity; and indexes on tenant, storage space, status, session and created time. Database privileges and repository APIs must make ingestion records/events append-only after insertion.

### 5. Treat provider state as authoritative for verification

Proxy and direct uploads finish with provider metadata verification. Multipart completion validates provider-visible parts and final object metadata; client ETags/lengths only narrow what must be checked. The adapter exposes normalized head/list-parts/complete/abort/version metadata.

The service verifies the command's physical key, actual length, content type, required checksum and version/ETag before committing. `StorageSpace.root_prefix` is joined once to canonical client-relative keys; no router, repository, or adapter may rederive a different physical key.

### 6. Use reconciliation rather than false success at the database/S3 boundary

Before external storage work, persist intent and a lifecycle event. If object storage succeeds but the final transaction fails, persist or reconstruct `reconciliation_required` using the session, request, idempotency key, and provider identity. A worker retries only idempotently, and no response reports an available file until commitment succeeds.

### 7. Apply mutation controls before work begins

File mutation commands include an idempotency fingerprint built from tenant, actor, endpoint, canonical body and canonical key. Existing idempotency keys are replayed only for the same fingerprint; mismatches return `409`. Entity changes compare `If-Match` with the persisted verified ETag/version before deletion or replacement.

HTTP routers forward `Idempotency-Key` and `If-Match` to the application command. Missing required headers and stale versions are rejected before MinIO calls. The idempotency record is written with the durable intent and is returned on a same-fingerprint retry.

## Risks / Trade-offs

- [Database and MinIO cannot commit atomically] → durable intent/events, reconciliation, and idempotent uniqueness constraints.
- [Stricter authorization changes currently accepted calls] → provide clear `401`/`403` behavior and integration fixtures for explicit delegation.
- [Provenance increases write volume] → append compact structured events, index tenant/session/status/time, and retain large diagnostics outside hot queries.
- [Credential provenance is sensitive] → record type and keyed fingerprint only; never tokens, secrets, or signed URLs.
- [Existing pending sessions lack new metadata] → mark them legacy/reconciliation-required on migration and expire or reconcile them safely.
- [Real integration tests can be accidentally configured with both direct and file-backed secrets] → construct isolated test settings with exactly one source per secret and fail preflight before any migration or fixture writes.

## Migration Plan

1. Add production identity-context provider and typed subject/credential provenance, then make missing or stale credentials fail closed.
2. Add migrations for context-safe session fields as needed, ingestion records/events, authorization evidence references, uniqueness constraints, and indexes.
3. Deploy read-compatible models, provider verification methods, and a reconciler before enforcing new completion writes.
4. Wire all file routes to authorized commands, creator/delegation checks, idempotency, and ETag validation; then enable verified completion and provenance creation.
5. Mark legacy pending sessions for explicit reconciliation/expiry; never auto-promote them to available.
6. Run the isolated real-infrastructure suite; roll back by disabling new writes and the reconciler while retaining append-only records and provider evidence.
