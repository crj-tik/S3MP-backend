## Purpose

为每个获授权的文件写入建立可追溯、可验证的入库事实链，使数据库中可用文件始终能关联到经验证的对象存储结果、执行主体和授权依据。

## ADDED Requirements

### Requirement: Durable ingestion lifecycle record
The system SHALL create a tenant-scoped ingestion record before it asks an object provider to perform an upload or multipart completion. The record SHALL retain the authorized relative key and derived physical key, storage space, acting and creator principals, authorization version and evidence, request identifier, idempotency identity, and an explicit lifecycle status.

#### Scenario: Authorized upload is initiated
- **WHEN** an authenticated principal successfully initiates an authorized upload or multipart upload
- **THEN** the system SHALL durably persist one `initiated` ingestion record before returning a provider instruction or accepting content

#### Scenario: A retry uses the same idempotency identity
- **WHEN** the same authenticated principal retries the same logical ingestion request with the same idempotency key and equivalent request semantics
- **THEN** the system SHALL return the original ingestion outcome without creating a second ingestion record

### Requirement: Verified commit and provenance events
The system SHALL transition an ingestion record to committed only after provider metadata has been verified against the authorized command. It SHALL persist provider ETag/version when available, actual size, actual content type, requested checksum verification result, and an append-only event for each terminal or security-relevant transition.

#### Scenario: Provider object matches the authorized upload
- **WHEN** the object provider reports an object whose key, size, content type, checksum requirement, and multipart completion state match the authorized command
- **THEN** the system SHALL atomically make the file available, mark the ingestion record committed, and append a committed event

#### Scenario: Provider object fails verification
- **WHEN** provider metadata is absent or differs from the authorized command
- **THEN** the system SHALL not make a file available, SHALL mark the ingestion record failed or quarantined, and SHALL append an event that records the non-sensitive verification reason

### Requirement: Referentially valid retention and cleanup
The ingestion schema SHALL preserve tenant integrity during upload-session or file cleanup. A deletion policy SHALL NOT attempt to set a non-nullable tenant identifier to NULL, and terminal provenance SHALL remain queryable for the configured retention period.

#### Scenario: An upload session is cleaned up
- **WHEN** a stale or aborted upload session is deleted
- **THEN** the database SHALL complete the deletion without violating a foreign-key or NOT NULL constraint and SHALL retain or remove the linked ingestion record according to its explicit retention policy
