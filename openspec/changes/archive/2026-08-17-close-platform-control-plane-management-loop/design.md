## Context

See `proposal.md` for motivation. The current implementation already separates
global `PlatformContext` from tenant `PrincipalContext`, creates platform roles
in `platform_role`, and can materialize a temporary tenant Membership through
two-person-approved Support Access. It lacks the read APIs needed to operate
those records, and its `platform_admin` baseline grants tenant management but
not the tenant-read permission checked by the listing APIs. Baseline seeding
currently creates missing roles but deliberately does not reconcile existing
roles. Support-expiry cleanup exists as a standalone script and is not owned by
the normal API/worker deployment lifecycle.

## Goals / Non-Goals

**Goals:**

- Make platform operations discoverable and usable without weakening tenant
  isolation.
- Reconcile built-in platform roles safely for already-initialized databases.
- Provide stable paginated control-plane DTOs and OpenAPI descriptions for the
  frontend.
- Make Support Access approval, entry, expiry, revocation, and audit a complete
  lifecycle.

**Non-Goals:**

- Grant platform roles automatic tenant permissions or automatic tenant session
  selection.
- Expose file contents, object credentials, API-key secrets, raw sessions, or
  detailed tenant data through platform listing APIs.
- Introduce a break-glass tenant write mode. Emergency write access requires a
  separately designed capability with stronger controls.
- Replace tenant-local member, group, role, or RoleBinding management APIs.

## Decisions

### Preserve two independent authorization contexts

Platform APIs will continue to resolve only `PlatformContext`, while tenant
APIs require `PrincipalContext`. A platform user may enter a tenant only through
an active normal Membership or an approved, unexpired Support Access Membership
and then calls the existing tenant-session selection operation.

This preserves tenant isolation and makes support access visible in the same
Membership, authorization-version, session-revocation, and audit mechanisms as
other tenant access. Treating a platform permission as an implicit tenant
superuser was rejected because it would bypass tenant authorization and make
support access difficult to reason about or revoke.

### Define explicit platform read permissions

Platform permission checks remain exact; `*.manage` does not imply `*.read`.
The platform permission vocabulary will include account, tenant, role,
Support-Access, and audit read permissions alongside the existing management
permissions. Built-in roles receive the least set needed for their operational
purpose, with `platform_admin` receiving all platform read and management
permissions.

This is preferred to changing the authorizer to infer read from manage because
implicit inheritance would be a hidden policy rule, obscure audits, and make
future role composition less predictable.

### Reconcile built-in roles idempotently

Startup/bootstrap will reconcile only named built-in platform role definitions:
it adds missing required permissions, leaves custom roles untouched, and never
removes an existing permission automatically. The reconciliation records a
platform audit event only when it changes a role. A migration or explicit
maintenance command will run the same idempotent logic for production data
before application rollout.

Add-only reconciliation avoids leaving existing administrators without newly
required reads. Automatic removal is rejected because it can unexpectedly
lock out a production operator and requires a separately approved revocation
process.

### Add a narrow, paginated platform control-plane read model

New read routes will live under `/api/v1/platform` and use cursor pagination
with filters appropriate to each resource:

| Resource | Required permission | Safe response contents |
|---|---|---|
| Accounts | `platform.accounts.read` | ID, name, email, employee number, status, timestamps |
| Roles and bindings | `platform.roles.read` | role names, permissions, binding IDs, user summary, expiry/revocation state |
| Support Access | `platform.support.read` | request ID, requester/approver summaries, target tenant, reason, status, expiry |
| Platform audits | `platform.audit.read` | audit ID, actor summary, action, resource, safe details, time |
| Tenants | `platform.tenants.read` | tenant ID, slug, name, lifecycle status, safe timestamps |

All routes will return `{items, next_cursor}` and reject callers lacking the
specific platform permission. Account responses intentionally omit credentials,
tokens and tenant-scoped permissions. Platform tenant summaries intentionally
omit application, file, S3 credential, and key material. A single unpaged or
global-tenant endpoint was rejected to prevent large enumeration responses and
to retain a consistent frontend data contract.

### Model Support Access states from persisted evidence

The Support Access read model derives a stable state: `pending`, `approved`,
`revoked`, or `expired`, with terminal state precedence `revoked` then
`expired`. It returns the materialized Membership and RoleBinding identifiers
only to authorized platform operators for recovery/audit actions; it never
returns their session tokens. Approval remains self-approval-resistant.

The approved support role stays read-only and excludes all file-content and
credential permissions. The frontend must refresh account context after
approval, display a tenant support banner with expiry, and require an explicit
tenant selection action.

### Own expiry processing in deployment

The existing expiry routine becomes a managed service responsibility: either a
dedicated lightweight scheduler container invoking the command at a bounded
interval, or a periodic task in the existing worker. The selected mechanism
must run once per minute in production, expose structured logs/metrics, and be
safe to run concurrently because revocation is idempotent.

A dedicated scheduler container is preferred: it keeps file-ingestion worker
throughput independent of control-plane cleanup, preserves one purpose per
process, and can be restarted/scaled independently. The worker-loop alternative
is rejected for this change because worker availability must not be a hidden
dependency of authorization cleanup.

## Risks / Trade-offs

- [Existing built-in roles may differ from code baseline] → Reconciliation is
  add-only, emits an audit event, and is verified in a staging copy before
  production rollout.
- [Account directory reveals PII to overly broad operators] → Use a dedicated
  `platform.accounts.read` permission, minimal DTOs, exact identifier filters,
  pagination, and platform audit events for sensitive administration actions.
- [Expired support session may exist briefly between scheduler runs] → Session
  resolution and authorization already validate Membership and binding expiry;
  the scheduler additionally revokes durable session records within one minute.
- [Two simultaneous schedulers revoke the same grant] → Use locked rows and
  idempotent state transitions; duplicate work must not create duplicate active
  access or fail the job.
- [Frontend assumes platform admin can edit tenant data] → Publish distinct
  control-plane and tenant APIs; show support access as time-bounded read-only
  access rather than a hidden tenant-admin shortcut.

## Migration Plan

1. Add platform read permissions, DTOs, repository queries, service methods,
   routes, OpenAPI documentation, and authorization tests.
2. Add the idempotent built-in platform-role reconciliation and a versioned
   database migration/maintenance command; execute it before enabling the new
   UI.
3. Deploy the dedicated Support Access expiry scheduler alongside API and file
   worker, then verify an approved expiring grant revokes Membership, binding,
   and tenant session.
4. Deploy frontend control-plane pages after the checked-in OpenAPI contract is
   generated and validated.
5. Roll back application routes/UI independently if needed. The add-only role
   permission migration is intentionally not automatically rolled back; remove
   permissions only through an explicit audited operational change.

### Make platform and probe response models resource-specific

Platform tenant endpoints will use `PlatformTenantResponse` and
`PlatformTenantPage`. The PATCH operation will validate `TenantUpdate` as its
request and return the updated `PlatformTenantResponse`. Role-binding and
Support Access queues will use their own paginated response models rather than
returning untyped dictionaries.

Storage connection probing will return a dedicated `ProbeResult` containing
`status`, `readable`, `writable`, `checked_at`, and optional safe
`failure_reason`. It will never return the `ProbeRequest` input model, a
credential reference, signature material, or a complete presigned URL.

### Close post-implementation control-plane correctness gaps

Every control-plane list is a real database page, not a response wrapper around
an unbounded or post-filtered collection. Repositories apply lifecycle and
search predicates before requesting `limit + 1` rows, order deterministically
by stable identifiers, and derive `next_cursor` only from the final matching
row set. The tenant and platform-role inventories receive the same limit and
opaque-cursor semantics already used by the other lists.

Opaque cursors are scoped to both their operation and normalized filter values.
A cursor issued for one account query, lifecycle status, Support Access status,
or audit action cannot be reused for another query. API routes validate known
lifecycle values at the HTTP boundary and return the standard validation error
for an unsupported value instead of allowing a repository enum conversion to
become a 500 response.

Account lookup preserves safe display-name search but treats email and employee
number as exact identifiers. Support Access queries join safe requester and
approver account summaries; they never expose credentials or session material.
The response retains the approver identifier for compatibility and adds the
approver summary when an approval exists.

Every control-plane route declares the exact operation identifier carried by
its authorization dependency. Contract verification accepts the operation only
when that identifier matches, rather than inferring it solely from a shared
permission string. This keeps permission-to-operation attribution auditable
when multiple routes require the same permission.

The dedicated scheduler exposes a `--once` execution mode that constructs its
normal store and runs one expiry pass. Compose health checks invoke that mode,
thereby proving the scheduler can connect to its real persistence dependency
and execute the idempotent expiry path instead of merely checking that PID 1
exists. Concurrent normal-loop and health-check expiry passes remain safe by
the existing idempotent lifecycle design.
