## Why

The current application derives tenant identity for most database queries, but several runtime boundaries do not enforce the intended authorization and storage-isolation guarantees. A tenant member or API Key can reach unguarded management endpoints, tenant storage spaces can overlap in the shared MinIO namespace, and delayed file work can survive membership revocation.

These gaps contradict the declared API permissions and the security invariants for directory-scoped access, application ownership, and immediate lifecycle revocation. They must be closed before the backend is treated as safe for multi-tenant use.

## What Changes

- Enforce declared management permissions for storage, quota, and audit operations at the HTTP and application-service boundaries; classify all management operations centrally so API Keys are denied before handlers run.
- **BREAKING** Derive every managed object key from a server-owned tenant and storage-space namespace, validate storage-space configuration, and reject legacy or overlapping mappings that cannot prove isolation.
- Revalidate human membership state and authorization version before delayed file execution, ingestion reconciliation, and deletion reconciliation.
- Close authorization-management escalation paths by enforcing permission delegability, self-grant prevention, delegated scope/expiry limits, immutable system roles, and revalidation when changing bound roles.
- Restrict file-operation visibility to the creator or a currently authorized delegated reader; return public response projections only.
- Make file-listing prefix queries observe canonical directory boundaries rather than lexical string prefixes.
- Detect and transition applications with no active Owner to pending takeover, including on membership lifecycle changes.
- Add adversarial integration tests and contract checks for all fixed boundaries.

## Capabilities

### New Capabilities

- `tenant-storage-isolation`: Provider-facing object namespace and storage-space configuration guarantees that prevent physical object overlap across tenants.

### Modified Capabilities

- `backend-file-storage`: Strengthen runtime management authorization, canonical directory listing, delayed-work reauthorization, and public file-operation visibility.
- `backend-identity-authorization`: Strengthen delegation rules and ensure membership lifecycle revocation reaches pending work.
- `backend-application-access`: Require active Owner evaluation and pending-takeover handling for orphaned applications.
- `runtime-contract-enforcement`: Require declared management permissions to be enforced consistently at runtime.

## Impact

- Affects storage, governance, authorization, identity, applications, files, worker, MinIO adapter, SQLAlchemy models/migrations, OpenAPI permission validation, and regression test suites.
- Existing storage-space mappings and file records need a controlled migration/compatibility audit because provider object keys will become namespaced.
- The externally documented paths remain stable; requests that previously relied on implicit access will receive `403 permission_denied`, and unsafe storage mappings will be rejected or quarantined.
