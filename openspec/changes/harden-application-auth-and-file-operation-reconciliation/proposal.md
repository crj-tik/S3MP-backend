## Why

The current implementation leaves two exploitable authorization gaps: an API Key is resolved with an application record ID instead of an application principal, and application/API-Key management operations lack authorization and scope enforcement. File-operation and ingestion recovery paths also persist intent but do not execute or re-authorize it reliably, leaving objects and PostgreSQL state unable to converge safely after failures or grant revocation.

## What Changes

- Make every application own a distinct enabled application principal, migrate existing application rows safely, and resolve API Keys to that principal only after validating the Key, application and principal lifecycle state.
- Enforce application-management permissions, ownership rules, API-Key endpoint restrictions and API-Key scope intersection at the HTTP and service boundaries. **BREAKING**: API Keys can no longer call management APIs, and applications without a valid principal become unavailable until migration/recovery completes.
- Correct management-list cursor progression and bind cursors to the authorized tenant, caller, query and authorization version.
- Introduce a durable PostgreSQL-backed file-operation worker with leasing, idempotent execution, retry/partial-failure states and execution-time re-authorization.
- Make ingestion and deletion reconciliation scheduled worker responsibilities that revalidate current subject state, authorization version and resource permissions before committing durable file state.

## Capabilities

### New Capabilities

- `file-operation-execution`: Durable, retryable execution and recovery of queued file copy, move and delete operations.

### Modified Capabilities

- `backend-application-access`: Require a distinct application principal and enforce authorized, scoped API-Key lifecycle and use.
- `backend-identity-authorization`: Make cursor pagination complete and authorization-version-bound for management resources.
- `backend-file-storage`: Require worker-driven file-operation execution and execution-time authorization revalidation.
- `file-ingestion-provenance`: Require recovery-time authorization revalidation before an ingestion record can commit a file.

## Impact

Affected areas include application/API-Key models, repositories, authentication middleware, authorization dependencies and OpenAPI contract metadata; identity pagination; file-operation and ingestion persistence; the FastAPI lifecycle; PostgreSQL migrations; Redis wake-up integration; MinIO recovery behavior; audit events; and real PostgreSQL/Redis/MinIO integration tests.
