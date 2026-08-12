## Why

The frontend contract scan shows that the normative OpenAPI schema has 64 operations, while the runtime FastAPI surface implements only a subset and most remaining modules have neither dependency wiring nor application-facing endpoints. Generated frontend types already match the schema, so the immediate risk is runtime drift: routes may be absent, return placeholder failures, or bypass tenant, authorization, concurrency, and audit semantics.

## What Changes

- Implement the complete declared `/api/v1` HTTP surface as vertically testable slices, rather than adding routers independently.
- Deliver concrete application services as the shared HTTP boundary: every use case receives PrincipalContext and coordinates authorization, tenant-scoped persistence, idempotency, ETags, storage, quota, audit, and recovery rather than leaving those concerns in routers.
- Complete the missing identity and authorization endpoints, then expose applications/API keys, storage/files/uploads/multipart, quota, and audit capabilities through tenant-scoped application services.
- Require every mutating operation to preserve the OpenAPI idempotency and ETag semantics, and every file-related operation to preserve exact authorization, S3 execution, quota, and audit boundaries.
- Add contract coverage that compares declared operation IDs with registered FastAPI routes and verifies representative success, denial, stale-write, tenant-isolation, and sensitive-data-redaction behavior.
- Keep the canonical backend contract unchanged for known frontend Mock defects: frontend must use `/applications/{application_id}/api_keys` and `authentication_required`, rather than introducing backend aliases or unofficial error codes.

## Capabilities

### New Capabilities

- `runtime-contract-enforcement`: Runtime operation coverage, request/response contract checks, and shared HTTP enforcement for tenant, idempotency, ETag, pagination, and stable errors.

### Modified Capabilities

- `backend-api-contract`: Every declared public operation becomes executable and contract-verified at runtime.
- `backend-identity-authorization`: Complete member/group membership and authorization explanation/simulation HTTP operations with tenant isolation.
- `backend-application-access`: Expose application and API key lifecycle operations through authorized HTTP endpoints.
- `backend-file-storage`: Expose storage, file, upload, multipart, quota, audit, and object-operation lifecycle endpoints without weakening storage or audit safeguards.

## Impact

- Adds application services, repository and external-service ports, composition-root wiring, API routers/Pydantic DTOs, recovery coordination, and contract/integration tests under `src/s3mp/**` and `tests/**`.
- Updates FastAPI application composition in `src/s3mp/main.py`; uses existing database, Redis, storage, quota, and audit abstractions rather than browser-visible S3 credentials. Development and integration tests use a locally deployed MinIO-compatible S3 endpoint through the object-storage port; credentials remain runtime secret references.
- No compatibility aliases are added for the two known frontend Mock defects; frontend Mock changes remain a coordinated downstream action.
