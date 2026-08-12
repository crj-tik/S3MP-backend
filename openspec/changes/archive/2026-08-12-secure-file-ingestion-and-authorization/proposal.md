## Why

The backend contains authorization primitives and file lifecycle tables, but they are not yet enforced as a single security boundary. An implementation review found that this change was incorrectly marked complete: session authentication is not production-wired, file workflows remain largely tenant-only, storage-space root prefixes are not applied, and verified ingestion provenance has no schema or migration. A protected file request therefore remains vulnerable to same-tenant session takeover, over-broad object access, forged multipart completion, and unauditable storage state.

## What Changes

- Establish a single trusted authentication boundary that derives `PrincipalContext` from server-verified session, API Key, or service credentials and rejects unverified protected requests.
- Enforce deny-first, tenant/space/prefix/action authorization for every file query, upload, download signature, multipart action, copy, move, delete, and recovery action.
- Bind uploads, multipart sessions, and file operations to their creator by default; permit delegated access only through an explicit, auditable authorization decision.
- Canonicalize client-relative object keys and derive one physical storage key from the storage space root prefix; authorization and MinIO execution use the same authorized command.
- Create a server-verified, immutable ingestion record and append-only event trail before exposing a file as available, including object metadata, authorization evidence, quota settlement, audit linkage, request correlation, and recovery state.
- Verify multipart completion from provider state rather than trusting client-supplied ETags or lengths, and recover database/S3 split failures without duplicate quota or file records.
- Apply idempotency and optimistic-concurrency protection to high-risk file mutations, with adversarial integration tests.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `backend-identity-authorization`: Require a trusted authentication boundary and resource-level authorization evidence for file actions.
- `backend-file-storage`: Require creator binding, canonical key derivation, provider-verified completion, and immutable ingestion provenance before availability.
- `durable-service-orchestration`: Require ingestion state/event recovery that prevents unverified success and duplicate settlement across the database/object-store boundary.
- `runtime-contract-enforcement`: Require protected file routes to apply authentication, authorization, idempotency, and ETag checks before application operations.

## Impact

- Affects app assembly, middleware/dependencies, identity and authorization services, file routes and application services, MinIO adapter, file/audit/quota persistence, migrations, and security test suites.
- Some previously permissive same-tenant operations will now return `401`, `403`, `404`, or `409` according to the caller, resource ownership, prefix scope, and mutation state.
- Adds ingestion provenance and append-only lifecycle records; existing incomplete uploads require reconciliation rather than being treated as available files.
- This change remains **unimplemented and pending convergence** until its tasks are verified against the actual HTTP-to-PostgreSQL/Redis/MinIO path. Task checkboxes are reset because prior completion marks did not reflect executable behavior.
