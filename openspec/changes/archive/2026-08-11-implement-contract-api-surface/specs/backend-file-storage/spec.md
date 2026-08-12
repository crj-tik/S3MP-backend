## ADDED Requirements

### Requirement: Executable file and governance lifecycle API
The service SHALL expose contract-declared storage, file, upload, multipart, object-operation, quota, and audit operations through tenant-scoped HTTP endpoints while preserving authorization, object-state, quota, and audit requirements.

#### Scenario: High-risk file operation cannot be audited
- **WHEN** a high-risk object mutation or signature issuance cannot durably record its audit event
- **THEN** the service SHALL reject the operation with `503 audit_unavailable` before reporting success

### Requirement: Coordinated object lifecycle services
File query, upload, multipart, object-operation, quota, and audit use cases SHALL execute through application services that use tenant-scoped persistence and object-storage ports. They SHALL persist operation intent before external storage work and SHALL record completed, failed, or partial-failure outcomes after verification.

#### Scenario: Source deletion fails after a verified move copy
- **WHEN** a move operation verifies its destination object but cannot delete the source
- **THEN** the object-operation service SHALL persist and return a recoverable `partial_failure` outcome rather than report complete success

### Requirement: Development MinIO object-storage verification
The development runtime SHALL support a MinIO-compatible object-storage adapter through the object-storage port, using explicit endpoint, region, bucket, and path-style configuration. Access credentials SHALL be supplied only through runtime environment-variable or secret-file references and SHALL NOT be persisted in source, audit events, API responses, or logs. Plain HTTP SHALL be accepted only in the explicit development environment.

#### Scenario: Development readiness validates object storage
- **WHEN** the development application starts with the local MinIO storage profile enabled
- **THEN** readiness SHALL perform only non-destructive bucket and permission checks and SHALL report storage unavailable when the configured bucket cannot be accessed

#### Scenario: Integration cleanup is isolated
- **WHEN** an object-storage integration test creates test objects
- **THEN** it SHALL use a unique test prefix and SHALL delete only objects under that prefix during cleanup
