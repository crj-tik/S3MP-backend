## 1. Local dependency configuration

- [x] 1.1 Add a secret-safe development S3 profile to backend deployment configuration for both host and Docker-network endpoint modes.
- [x] 1.2 Update deployment documentation and examples to describe PostgreSQL, Redis, and independent MinIO startup, endpoint selection, and migration ordering without credential values.
- [x] 1.3 Add configuration validation tests for enabled S3 profiles, production secret-file requirements, and invalid endpoint/bucket combinations.

## 2. Runtime readiness and migrations

- [x] 2.1 Make the API readiness surface report PostgreSQL, Redis, and enabled MinIO status independently with bounded timeouts.
- [x] 2.2 Add an explicit migration execution path that completes before the API is accepted as ready and fails visibly on migration errors.
- [x] 2.3 Add host-mode and container-network integration checks for the three dependency endpoints.

## 3. Redis-backed coordination

- [x] 3.1 Implement Redis-backed idempotency storage with request fingerprint, replay/conflict response, TTL, and process-restart tests.
- [x] 3.2 Implement Redis-backed login/API-key rate limiting and replace runtime use of process-local fallback implementations.
- [x] 3.3 Implement Redis worker leases/outbox coordination adapters with retry-safe ownership and cleanup behavior.

## 4. Validation

- [x] 4.1 Run the local Compose dependency profile, migrations, readiness checks, lint/type checks, and unit/integration suites.
- [x] 4.2 Verify that tracked configuration, logs, and API responses contain no database, Redis, or S3 credential values.