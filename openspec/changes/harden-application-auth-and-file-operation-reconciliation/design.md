## Context

See `proposal.md` for motivation and the delta specs for required behavior. The current application record stores a human creator principal rather than an independent machine principal, while API-Key authentication currently returns the application record ID as a principal ID. File authorization expects real principals. Management list repositories also use the look-ahead row as the cursor, which skips that row. File operations and reconciliation records are durable but have no scheduled consumer; reconciliation trusts historical authorization evidence instead of current authorization.

## Goals / Non-Goals

**Goals:**

- Establish one canonical application principal identity for every API-Key request and require all authorization decisions to use it.
- Make management and machine endpoint access default-deny at both HTTP and service boundaries.
- Provide lossless, context-bound cursor pagination.
- Make queued object operations and recovery records durable, leased, retryable, re-authorized and observable.
- Preserve PostgreSQL as the source of truth while using Redis only to reduce worker pickup latency.

**Non-Goals:**

- Adding an external message broker or changing the public file-operation request/response paths.
- Revoking already-issued MinIO presigned URLs before their expiry.
- Providing exactly-once provider calls; the design instead requires idempotent, verified effects and recoverable state transitions.

## Decisions

### 1. Separate business application IDs from authorization principal IDs

Add/retain `application.principal_id` as a required foreign key to `principal(type=application)`. Application creation creates the principal, application and first owner in one transaction. A migration creates one enabled principal per legacy application, updates the foreign key, records a migration audit event and marks ambiguous or invalid rows unavailable rather than falling back to a human principal.

API-Key lookup joins key, application and principal and returns an access context containing `principal_id`, `application_id`, `api_key_id`, scopes and a monotonic authorization version. It rejects inactive/expired/revoked Key, inactive application and disabled principal. This is selected over treating `application.id` as the principal because UUID equality cannot express the distinct lifecycle or binding domain.

### 2. Centralize endpoint class and effective permission calculation

Classify endpoints as human-management or machine-resource endpoints. Authentication rejects API Keys for the former before routing. For machine-resource endpoints, a shared authorization adapter calculates `declared endpoint permission ∩ key scopes ∩ RoleBinding decision ∩ canonical storage scope`; explicit deny wins. Application/Key lifecycle services repeat target authorization and Owner checks for non-HTTP callers. This replaces unused helper-only scope checks and router-only authorization.

### 3. Version application authority and bind pagination cursors

Introduce a principal authorization version for applications (or a version record keyed by tenant/principal) and increment it atomically when application state, Key state, group membership or relevant RoleBinding changes. Persist the version in operation/ingestion intent. Revalidation reads the current version and reruns authorization.

List repositories retain `limit + 1` for look-ahead but encode the last returned row as the next cursor. The signed/opaque cursor payload includes tenant, requester principal, requester authorization version, normalized filter, sort discriminator and last returned key. A mismatch fails validation instead of changing query semantics.

### 4. Use PostgreSQL leasing for durable workers; Redis only signals work

Extend `file_operation` with authorization evidence, canonical source/destination set, state, attempt count, lease owner/until, next retry time, terminal error and timestamps. A worker claims ready work through transactionally locked PostgreSQL rows (`SKIP LOCKED`), executes idempotently against MinIO, and writes a terminal or retry state. Redis publishes a wake-up after enqueue/transition, but periodic PostgreSQL polling handles missed notifications and Redis outages.

This is preferred over FastAPI in-process background tasks because web replicas can duplicate work and shutdown loses execution. It is also preferred over Redis-as-queue because operation state must survive Redis loss and remain auditable.

### 5. Revalidate before delayed object effects and final ingestion commit

Create an authorization revalidator that reconstructs the persisted operation identity without using caller-controlled data. It checks human membership/session-independent principal validity or application/Key validity, current version, effective permission and the persisted canonical storage scope. The operation worker invokes it before each object side effect; ingestion recovery invokes it before `commit_verified_file`. Failure records `cancelled`, `failed` or `quarantined` with redacted audit detail and schedules controlled object cleanup where appropriate.

Deletion and ingestion reconciliation are worker jobs with a bounded retry policy and a queryable terminal state. They are not run as unbounded request-time retries.

### 6. Deploy security closure before enabling workers

Deploy migrations and dual-read support first, backfill application principals, verify invariants, then enforce the corrected API-Key context and management restrictions. Only after that enable operation/reconciliation workers; otherwise queued legacy records could execute under ambiguous authority. Existing pending records lacking enough authorization identity are quarantined for operator review rather than auto-executed.

## Risks / Trade-offs

- [Legacy application rows cannot be mapped safely] → Mark unavailable, emit an audit/report record and require administrator remediation; never impersonate the original creator.
- [Worker crash after MinIO success but before PostgreSQL result] → Verify source/destination object state on retry and use deterministic operation identity before repeating side effects.
- [Redis unavailable] → Continue periodic PostgreSQL polling; readiness exposes degraded wake-up capability but does not discard work.
- [Authorization checks add database reads] → Use short-lived version-aware caching only after correctness tests, and invalidate by version rather than using TTL as security control.
- [Changing API-Key access breaks current clients] → Publish the management-endpoint restriction as a breaking change and provide pre-deployment usage audit.

## Migration Plan

1. Add additive schema fields/tables, application-principal backfill and operation worker columns without enabling strict behavior.
2. Run an invariant report: every active application has one enabled application principal; every active Key resolves to it; invalid rows are disabled/quarantined and audited.
3. Deploy authentication and authorization enforcement, then run real PostgreSQL/Redis/MinIO acceptance tests before allowing external API-Key traffic.
4. Enable worker polling and Redis wake-ups; migrate only sufficiently attributed pending records and quarantine legacy ambiguous work.
5. Monitor terminal-state age, lease expiry, reauthorization cancellations and reconciliation backlog; enable alerts before declaring completion.

Rollback application code by disabling worker consumption and redeploying the previous version only before strict authentication is enabled. Database additions are additive; do not roll back principal migration by deleting principals, operations, ingestion provenance or audit evidence.

## Open Questions

- The exact permission names for application and API-Key lifecycle management must be aligned with the existing permission catalog during implementation; this does not change the requirement that every lifecycle operation is explicitly authorized.
- The configured retry budget and retention duration can be selected from operational requirements without changing the state machine or authorization semantics.
