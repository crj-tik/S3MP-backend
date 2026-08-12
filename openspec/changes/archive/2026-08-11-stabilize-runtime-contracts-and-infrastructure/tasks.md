## 1. Regression Baseline and Contract Alignment

- [x] 1.1 Add failing regression coverage for application creation with its initial owner, repeated API Key secret lookup, runtime OpenAPI prefix drift, missing authenticated context, and currently lossy Redis outbox cases.
- [x] 1.2 Update `contracts/openapi.yaml` so all public operations use the canonical `/api/v1` paths and verify methods, response statuses, and operation IDs match runtime registration.
- [x] 1.3 Change repeated API Key secret lookup to return `410 secret_not_retrievable` using the standard error envelope, and add contract-level coverage for the catalogued code.
- [x] 1.4 Strengthen `scripts/check_openapi.py` and its tests to compare runtime and baseline paths, methods, response statuses, and registered public error codes bidirectionally.

## 2. Application Persistence and Authenticated Runtime Composition

- [x] 2.1 Repair application creation so the generated application identifier is persisted before the initial owner relation is created, with atomic rollback on owner persistence failure.
- [x] 2.2 Replace fixed API Key credential material in app assembly with a validated environment/secret-file setting supporting explicit pepper versioning.
- [x] 2.3 Implement the request authentication boundary that resolves credentials to a verified `PrincipalContext` and rejects protected calls without valid context.
- [x] 2.4 Wire all protected routers to tenant-scoped application services through the verified context; prevent runtime use of `_NoopStore` or unconfigured service fallbacks for enabled protected APIs.
- [x] 2.5 Add HTTP and PostgreSQL integration tests for valid context, missing/invalid context, tenant isolation, application creation, owner persistence, and API Key lifecycle behavior.

## 3. S3/MinIO File Lifecycle and Durable Coordination

- [x] 3.1 Expand the object-storage port and MinIO adapter to provide normalized verified metadata, presigned PUT/GET, multipart create/upload-part/list/complete/abort, copy, delete, and readiness operations using configured bucket and path-style settings.
- [x] 3.2 Refactor upload completion and download signing services to use the object-storage port, verify object state, persist verified metadata, and remove placeholder storage URLs.
- [x] 3.3 Implement multipart lifecycle coordination with durable upload/session state, quota reservation and settlement, and verified final object creation.
- [x] 3.4 Implement copy, move, and delete coordination with pre-operation intent, redacted audit recording, verified outcomes, and persisted `partial_failure` recovery state when source deletion fails after copy.
- [x] 3.5 Wire file command services, object storage, quota, audit, and operation repositories into app assembly and public file routes without router-level persistence or storage access.
- [x] 3.6 Add PostgreSQL/MinIO integration tests covering upload completion, presigned download, multipart completion/abort, copy, move partial failure, delete, quota settlement, and redacted audit events.

## 4. Redis Outbox and Coordination

- [x] 4.1 Introduce stable outbox event identifiers, Redis Stream producer/consumer-group configuration, acknowledgement, pending-message claim, bounded retry, and dead-letter handling.
- [x] 4.2 Add an outbox worker/recovery entry point with explicit failure logging, metrics/readiness exposure, and idempotent handler contract.
- [x] 4.3 Replace multi-command rate-limit admission with an atomic server-side operation and deterministic member identity.
- [x] 4.4 Add Redis integration tests for acknowledgement, lease recovery, negative acknowledgement retry/dead-letter behavior, duplicate handling, and concurrent rate-limit boundary admission.

## 5. Local Infrastructure Profile

- [x] 5.1 Consolidate PostgreSQL, Redis, MinIO, bucket initialization, migration execution, and API startup into one documented local development Compose profile with dependency health checks.
- [x] 5.2 Move all credentials to environment or secret-file references; remove tracked credential defaults from runtime and test configuration while retaining documented variable names and non-secret examples.
- [x] 5.3 Add startup/preflight checks that report enabled PostgreSQL, Redis, and MinIO failures independently and prevent readiness until migrations and dependency checks succeed.
- [x] 5.4 Create explicit `S3MP_TEST_*` infrastructure configuration, dependency preflight, and a destructive migration guard that refuses unspecified or non-test database targets.
- [x] 5.5 Document local startup, secret provisioning, test isolation, preflight, migration, cleanup, and recovery procedures.

## 6. Quality Gates and Verification

- [x] 6.1 Resolve Ruff violations in runtime code and touched tests, and configure the gate so its scope and remaining debt are explicit.
- [x] 6.2 Diagnose and fix the Mypy internal failure; make type checking deterministic for runtime code and the touched test/infrastructure modules.
- [x] 6.3 Run contract checks, focused regression suites, PostgreSQL/Redis/MinIO integration suites, Ruff, Mypy, and the complete pytest suite in the documented isolated profile.
- [x] 6.4 Record final command outputs, known exclusions, dependency versions, and any remaining follow-up debt in the change verification notes before marking the change complete.