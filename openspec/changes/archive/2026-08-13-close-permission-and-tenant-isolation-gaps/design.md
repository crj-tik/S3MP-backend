## Context

See [proposal.md](proposal.md) for motivation. The current system has three materially different enforcement planes:

1. PostgreSQL repositories usually filter `tenant_id`, which prevents most identifier-based cross-tenant reads.
2. HTTP management authorization is opt-in through a finite operation map, leaving storage, quota, and audit endpoints outside the map.
3. File authorization checks canonical relative keys, while MinIO receives a string key in one globally configured bucket. Storage-space `bucket` and `root_prefix` data is not a provider isolation boundary.

The change must repair all three planes without treating database tenant filtering as a substitute for authorization or provider isolation. Existing file records persist physical keys, and durable work can outlive a session, so migration and delayed-work behavior are security-critical.

## Goals / Non-Goals

**Goals:**

- Make tenant/storage-space ownership intrinsic to every MinIO object target.
- Make every contract-declared management permission enforceable and testable at both HTTP and service boundaries.
- Make revocation, delegation, operation visibility, and Owner lifecycle consistent across synchronous and delayed execution.
- Produce deterministic migration audit results rather than silently rewriting ambiguous data.

**Non-Goals:**

- Introducing external IAM/STS, per-tenant MinIO credentials, or a new public API version.
- Retroactively making already-issued presigned URLs revocable; their documented bounded exposure window remains unchanged.
- Building the existing access-review product surface beyond the lifecycle triggers required to identify and contain orphan applications.

## Decisions

### 1. Namespace provider keys with immutable tenant and storage-space IDs

All provider operations will accept a `ProviderTarget(bucket, key)` derived from an authorized storage-space record. The key format will be versioned and server-owned, for example `v1/tenants/<tenant-uuid>/spaces/<space-uuid>/<relative-key>`. `root_prefix` becomes an optional operator-owned segment beneath the immutable namespace only after canonical validation; it cannot replace or escape that namespace.

The adapter will receive the target bucket instead of holding the global bucket as the only runtime target. The configured default bucket is retained only as development/bootstrap configuration when no per-space provider target exists.

Alternative considered: enforce globally unique `(bucket, root_prefix)` in PostgreSQL. Rejected because it cannot prove isolation if an operator changes provider configuration outside PostgreSQL, does not make keys self-describing, and blocks legitimate same-bucket use without providing a safe namespace.

### 2. Migrate by audit and explicit target version, not in-place guesswork

Add a target-version field to storage spaces and persistent work/file records that require provider I/O. A migration command will classify records as safe-to-rewrite, safe-to-read-legacy-only, or quarantined. No delayed mutation may use legacy unscoped data. For records that can be deterministically mapped, copy objects to the new target, verify metadata, update persistence in one transaction, and emit audit events; deletion of old objects is a separate, resumable cleanup phase.

Alternative considered: prefix all future keys and leave old records active. Rejected because it preserves a cross-tenant mutation path in workers and reconciliation.

### 3. Generate one runtime authorization classification from the OpenAPI contract

Extend contract verification to require every non-public `x-permission` operation to be classified as either `machine_resource` or `management`. A single registry will drive the FastAPI dependency, API-Key pre-handler denial, and coverage test. Storage and governance handlers will accept `PrincipalContext`, while their application services receive an authorizer and enforce the same permission for non-HTTP callers.

File/data-plane operations remain machine-resource operations: API Key access is possible only through scope intersection and resource authorization. Identity, authorization, application, API Key, storage connection/space, quota, audit, and access-review operations are management operations.

Alternative considered: expand the existing path-prefix blacklist. Rejected because `/storage_spaces` contains both management and file data-plane paths, so prefix matching either over-blocks legitimate API Key file calls or misses management routes again.

### 4. Treat delegation as authority transformation, not only binding creation

Add a delegation policy resolver backed by the permission catalog's `delegable` field and current effective bindings. It will validate role creation, role update, and role binding creation. A role permission update computes added permissions and evaluates every active binding scope that would receive them. Built-in roles are immutable. New/changed bindings must be non-self-granting, a permission and scope subset, and expire no later than the caller's delegable grant(s).

The same policy will be used for revocation decisions where target-specific authority is required. All denied escalation attempts emit a redacted security audit event.

Alternative considered: disallow all edits to bound roles. Rejected because it creates unnecessary administrative churn; scope-aware revalidation retains safe updates while preserving the current model.

### 5. Use an explicit current-subject validator for delayed work

Create a shared validator for ingestion reconciliation, deletion reconciliation, and file-operation workers. For human subjects it loads the persisted membership identity, requires active/non-expired status, and requires current authorization version equality before calculating current permissions. For applications it verifies Key, application, and application-principal lifecycle/version. It then evaluates each affected relative key against current bindings.

The durable operation/ingestion data must persist the human membership ID in addition to the principal ID. Tasks created before this change without enough identity information are cancelled/quarantined instead of being inferred from a principal with potentially multiple memberships.

Alternative considered: use only current bindings after a principal lookup. Rejected because a suspended membership can leave the principal enabled and bindings present.

### 6. Separate public projections from internal durable records

Repositories may continue returning internal records to application services, but API responses use typed public projection functions. Operation reads default to creator-only; a non-creator needs current authorization for all source/destination/delete keys, evaluated against the operation's storage space. Internal tenant IDs, principals, idempotency fingerprints, lease/retry state, provider IDs, and authorization evidence never cross the HTTP boundary.

File listings use `object_key = prefix OR object_key LIKE escaped(prefix + '/%')`; authorization uses the relative key while persistence queries use the corresponding derived physical prefix. This prevents both similar-prefix disclosure and accidental mismatch between data storage and authorization representation.

### 7. Recompute active application Owners on lifecycle events

Introduce an Owner-state service/repository query that joins application owners to active human memberships/principals (and active group membership if group Owners are supported by the persisted model). Member status changes invoke it transactionally for affected applications; a governance scan catches legacy drift. Transitioning to `pending_takeover` increments the application authorization version, disables new API-Key authentication, emits an audit/outbox event, and requires an authorized takeover flow to reactivate.

Alternative considered: detect orphaning only when an application is accessed. Rejected because a compromised Key could remain usable until an unrelated management action occurs.

## Risks / Trade-offs

- [Existing objects require copy/migration and may temporarily consume double storage] → migrate in batches, verify every copy, preserve an immutable manifest, and defer old-object deletion until explicit approval.
- [Object key format is breaking for direct consumers] → public APIs continue accepting relative keys; document that provider keys are internal and use an adapter compatibility mode only for verified read-only migration operations.
- [Central operation registry can drift from routes] → contract verification fails CI when a declared permission lacks classification, and integration tests execute both a denied and permitted call for every management category.
- [Owner transition could lock a legitimate application during identity outages] → use transactional status transitions for known lifecycle events; scanner findings require repeatable evidence and emit a reversible pending state rather than deleting the application.
- [More revalidation queries add worker latency] → batch cache only positive membership/principal reads by version inside one worker run; authorization remains authoritative in PostgreSQL.

## Migration Plan

1. Add additive schema fields/tables for provider-target version, persisted membership identity for durable work, application pending-takeover state, and audit/outbox records.
2. Deploy read-path support that understands both target versions but refuses legacy records for delayed mutation.
3. Run a dry-run audit that reports root-prefix overlap, unscoped objects, unsafe task records, role/binding delegation violations, orphan applications, and management registry omissions.
4. Repair or quarantine unsafe records; migrate verified objects into namespaced targets with copy-and-head verification and durable manifests.
5. Enable namespaced writes, strict management authorization, delayed-subject validation, and delegation checks behind a migration-complete guard.
6. Execute adversarial PostgreSQL/Redis/MinIO integration tests and contract validation before removing verified legacy read compatibility.

Rollback: application code can temporarily restore verified legacy read support, but it MUST NOT restore legacy writes, provider mutations, or implicit management authorization. Additive database fields and migrated objects are retained; rollback is operational rather than destructive.

## Open Questions

- The current storage-space API has no update/delete operation. The implementation will validate creation and migrate persisted records; a future operator-only remediation endpoint is not required for this change.
- Group Owner persistence is not present in the inspected `application_owner` model. This change will enforce current direct-owner semantics and leave group-owner schema expansion out of scope unless existing data reveals such rows.
