## 1. Unit conversion boundary

- [x] 1.1 Add a single GiB-to-bytes conversion helper with integer, finite, non-negative validation.
- [x] 1.2 Rename the shared Bucket environment variable to `S3MP_S3_BUCKET_CAPACITY_GIB` and update Settings loading and startup diagnostics.
- [x] 1.3 Add stable GiB formatting for response fields without using formatted values for persistence.

## 2. API and service contract

- [x] 2.1 Change platform quota create/update request bodies from `limit_bytes` to `limit_gib`.
- [x] 2.2 Add GiB fields to quota detail/list responses and preserve exact internal bytes only as explicitly documented diagnostics.
- [x] 2.3 Reject old `limit_bytes` input and validate tenant/application/Bucket limits after conversion.
- [x] 2.4 Update tenant-facing quota responses and metadata catalog descriptions to use GiB consistently.

## 3. Persistence and runtime behavior

- [x] 3.1 Keep PostgreSQL limit/usage/reservation columns in bytes and ensure all reservation, settlement, deletion and reconciliation paths remain byte-based.
- [x] 3.2 Verify Bucket capacity is injected into platform quota services after GiB conversion.
- [x] 3.3 Add startup configuration validation so production S3 deployments cannot silently run without a Bucket ceiling.

## 4. Contract and deployment updates

- [x] 4.1 Regenerate `contracts/openapi.yaml` and remove public byte input fields.
- [x] 4.2 Update error codes, permission/metadata catalogs and Chinese Swagger descriptions.
- [x] 4.3 Update `deploy/.env.example`, compose files and deployment documentation.

## 5. Tests and rollout

- [x] 5.1 Add conversion tests for exact boundaries, invalid values and non-integer usage display.
- [x] 5.2 Add HTTP tests for GiB request/response shapes and rejection of legacy byte fields.
- [x] 5.3 Run migration, OpenAPI, Ruff, Mypy, full pytest and container readiness checks.
- [x] 5.4 Document the frontend migration and verify no runtime client still sends `limit_bytes`.
