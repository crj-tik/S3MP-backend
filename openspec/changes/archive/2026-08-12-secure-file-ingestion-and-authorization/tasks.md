## 1. Restore a Trustworthy Security Baseline

- [x] 1.1 Replace the incorrect completion claim with focused failing regressions for missing/invalid credentials, stale authorization versions, same-tenant session takeover, explicit deny precedence, out-of-prefix access, forged multipart input, stale ETag deletion, and idempotency-key reuse with changed input.
- [x] 1.2 Fix real-infrastructure test settings so every secret has exactly one source, then prove the PostgreSQL/Redis/MinIO preflight and file E2E setup can start without configuration validation errors.

## 2. Production Authentication and Subject Semantics

- [x] 2.1 Implement and register a production `identity_context_provider` that resolves server-side sessions, verifies revocation/expiry, active user/principal/membership state, and current authorization version.
- [x] 2.2 Extend the request context with subject kind and non-secret credential provenance; model application/API-Key contexts without substituting an application ID for a membership ID.
- [x] 2.3 Make production authentication fail closed for all protected routes, retaining only explicit health/bootstrap exemptions; move principal-context injection to test-only app construction or dependency overrides.
- [x] 2.4 Add HTTP integration tests for session authentication, API-Key authentication, credential revocation, membership suspension, and authorization-version advancement using production app wiring.

## 3. Resource Authorization and Canonical Storage Commands

- [x] 3.1 Implement a file authorization service that resolves current direct/group bindings by subject kind and applies deny-first tenant, storage-space, prefix, action, validity, and revocation checks.
- [x] 3.2 Persist non-secret authorization evidence including decision, reason, binding identifiers, policy/authorization version, actor, credential fingerprint, and evaluation timestamp.
- [x] 3.3 Define `AuthorizedFileCommand` and canonical key helpers so `physical_key = join(storage_space.root_prefix, relative_key)` is computed once and shared by authorization, persistence, signing, and MinIO execution.
- [x] 3.4 Refactor file services and the MinIO adapter so no public file operation accepts an unverified key, bucket, or action outside an authorized command.
- [x] 3.5 Add adversarial tests for traversal, encoded ambiguity, root-prefix isolation, similar-prefix bypass, explicit deny overriding allow, and no-MinIO-call-on-denial behavior.

## 4. Creator, Delegation, and Mutation Controls

- [x] 4.1 Pass `PrincipalContext` and request correlation to every upload, multipart, file-operation, file read/delete, download-signing, and recovery service method; remove bare tenant-only mutations.
- [x] 4.2 Enforce creator ownership on all workflow reads and mutations, and permit a non-creator only through explicit delegated resource authorization while recording creator and actor.
- [x] 4.3 Forward `Idempotency-Key` and `If-Match` from all high-risk file routes, persist canonical tenant/actor/endpoint/body/key fingerprints, and return the established result or `409 idempotency_key_reused` correctly.
- [x] 4.4 Persist verified ETag/version metadata and reject stale `If-Match` before database or MinIO deletion/replacement work.
- [x] 4.5 Add HTTP and PostgreSQL tests for cross-principal upload/multipart/operation takeover, delegated completion, replay safety, and stale ETag no-side-effect behavior.

## 5. Verified Ingestion Provenance and Atomic Settlement

- [x] 5.1 Create migrations and ORM models for immutable `file_ingestion_record` and append-only `file_ingestion_event`, with session, actor/credential, storage/provider metadata, authorization evidence, quota/audit/outbox links, status, indexes, and uniqueness constraints.
- [x] 5.2 Extend repositories with locked creator-aware session lookup, intent/event append, idempotent committed-record lookup, provider identity persistence, immutable provenance insert, and file projection mutation methods.
- [x] 5.3 Implement the ingestion state machine (`initiated`, `uploading`, `verification_pending`, `verified`, `committed`, `available`, `failed`, `expired`, `reconciliation_required`) and prohibit available files without committed provenance.
- [x] 5.4 Commit verified file projection, quota settlement, redacted audit event, outbox event, provenance record/event, and session terminal state in one database transaction; prevent duplicate durable effects with uniqueness and locks.
- [x] 5.5 Migrate existing pending/incomplete sessions to explicit legacy reconciliation or expiry states and prove no legacy record is auto-promoted to available.

## 6. Provider Verification, Recovery, and Acceptance

- [x] 6.1 Expand the MinIO port to expose normalized object length/type/etag/checksum/version metadata and authoritative multipart create/list-parts/complete/abort operations.
- [x] 6.2 Verify upload completion against the authorized physical key and provider metadata before committing ingestion; use provider metadata rather than declared client fields for `file_object` evidence.
- [x] 6.3 Verify multipart part lists and final object state from MinIO; reject client ETag/length assertions that disagree with provider state.
- [x] 6.4 Implement an idempotent reconciler for `reconciliation_required` records that resumes settlement without duplicate file objects, quota effects, audit events, or outbox messages; provide privileged recovery/audit visibility.
- [x] 6.5 Run migrations, contract checks, focused attack suites, and full PostgreSQL/Redis/MinIO integration tests; then run Ruff and Mypy and record commands/results before marking this change complete.
