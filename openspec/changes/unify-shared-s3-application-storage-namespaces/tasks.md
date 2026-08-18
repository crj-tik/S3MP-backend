## 1. Baseline and migration inventory

- [x] 1.1 Inventory current storage connections, spaces, applications, files, uploads, multipart sessions, ingestion records, operations, role bindings and quota rows, and document the legacy-to-new mapping keys.
- [x] 1.2 Add migration audit output for missing application ownership, duplicate tenant/application namespaces, overlapping root prefixes, invalid physical keys and orphan provider records.
- [x] 1.3 Define quarantine and audit outcomes for records that cannot be mapped safely; ensure quarantined records cannot be read, signed, mutated or counted as available usage.

## 2. Shared S3 profile and storage namespace model

- [x] 2.1 Add the platform-level shared S3 profile model, repository and lifecycle configuration with endpoint, region, bucket, path-style, signature version, credential reference and profile version.
- [x] 2.2 Add idempotent startup/health validation for the active shared profile and ensure new requests cannot select a tenant-supplied Bucket, Region or Endpoint.
- [x] 2.3 Add application-to-storage-space one-to-one binding and an immutable storage namespace, including tenant/application uniqueness and active lifecycle checks.
- [x] 2.4 Update storage DTOs and services so Bucket/Region are server-derived and application namespace is returned as metadata without exposing credentials.
- [x] 2.5 Add database migrations and data backfill for shared profile, application bindings and namespace versions; preserve legacy fields as read-only migration evidence until cutover.

## 3. Provider target and file-operation integration

- [x] 3.1 Replace tenant/storage-space provider target derivation with shared Bucket plus server-owned tenant/application namespace plus canonical relative key.
- [x] 3.2 Make upload, direct upload completion, multipart part/complete/abort, download, list, delete, copy/move and presigning use the same derived target and reject caller-supplied physical targets.
- [x] 3.3 Persist application_id, namespace, profile version and derived target evidence in upload, multipart, ingestion and file-operation records.
- [x] 3.4 Update workers and delayed subject validation to recheck tenant/application lifecycle, authorization version, API Key scope and profile version before provider mutation.
- [x] 3.5 Add compatibility handling for legacy records and fail closed when a queued or persisted target cannot be proven to belong to one tenant/application namespace.

## 4. Group and application authorization

- [x] 4.1 Extend scoped RoleBinding validation and projections to require an application/storage-space scope for file permissions and to verify tenant/application ownership.
- [x] 4.2 Ensure user group principals grant permissions only through active group membership; keep groups non-authenticating with no password, session or API Key flow.
- [x] 4.3 Ensure application API Keys resolve only to their application principal and cannot inherit ordinary user group memberships or access another application namespace.
- [x] 4.4 Add application-path authorization tests for direct user grants, group grants, application grants, deny precedence, prefix boundaries, cross-tenant IDs and cross-application IDs.
- [x] 4.5 Advance authorization versions and revoke/revalidate affected sessions and queued work when group membership, application state or scoped bindings change.

## 5. Quotas, reservations and reconciliation

- [x] 5.1 Add tenant and application quota fields for limit, used bytes, reserved bytes and update/version metadata, with validation that application allocations fit tenant capacity.
- [x] 5.2 Implement atomic reservation at upload and multipart-session creation under tenant and application quota locks.
- [x] 5.3 Implement idempotent reservation settlement for commit, failure, abort and expiry using provider-verified actual object size.
- [x] 5.4 Reject, quarantine or controlled-delete objects whose verified size exceeds application or tenant quota; emit non-sensitive audit events.
- [x] 5.5 Add tenant/application usage and remaining-capacity response models and reconciliation command/task with orphan and conflict reporting.
- [x] 5.6 Test concurrent upload races, retry idempotency, worker restarts, expired reservations and reconciliation correction.

## 6. API contract and operational rollout

- [x] 6.1 Add or revise OpenAPI schemas and Chinese descriptions for shared profile, application storage namespace, application-path grants, quota status and reconciliation results.
- [x] 6.2 Mark tenant-configurable Bucket/Region/Endpoint request fields deprecated before removing them, and document the migration response and compatibility window.
- [ ] 6.3 Update frontend-facing management contracts for application storage, group path grants and quota dashboards without adding login behavior to groups.
- [x] 6.4 Add deployment configuration, secret references and startup checks for the single shared S3 profile; verify path-style and region behavior for MinIO and production S3.
- [x] 6.5 Execute migration dry-run, shared-bucket namespace smoke tests, cross-tenant/cross-application adversarial tests, quota tests and contract checks before enabling writes.
- [x] 6.6 Complete cutover, monitor quarantined records and provider failures, then remove tenant write access to legacy connection fields after the rollback window.
- [x] 6.7 Add `GET /api/v1/metadata/catalog` as a versioned read-only enum/state catalog; share one server-side enum source with OpenAPI generation, document Chinese labels and transitions, cover storage/authorization/file/quota/lifecycle values, and add contract plus runtime regression tests.
