## ADDED Requirements

### Requirement: Creator-bound file workflow access
Upload sessions, multipart sessions, and file operations SHALL be bound to their creating principal. A different principal MUST be rejected unless it has an explicit effective permission for that resource and action; authorization failures SHALL be recorded without exposing the resource to the caller.

#### Scenario: Same-tenant caller attempts session takeover
- **WHEN** a principal attempts to read, upload to, complete, abort, or enumerate another principal's upload or multipart session
- **THEN** the service SHALL deny the request and SHALL not change the session or object state

#### Scenario: Delegated administrator completes a session
- **WHEN** a different principal has explicit effective delegated permission for the relevant storage space, key, and completion action
- **THEN** the service SHALL permit completion and SHALL record both the creator and acting principal in the lifecycle evidence

### Requirement: Unified canonical object identity
The service SHALL accept only a canonical relative object key, derive the physical object key by applying the storage space root prefix once, and use that same storage-space, bucket, relative key, physical key, and action for authorization, persistence, signing, and object-storage execution.

#### Scenario: Client submits a non-canonical key
- **WHEN** a client submits a key with traversal, backslashes, encoded ambiguity, control characters, or an invalid segment
- **THEN** the service SHALL reject the request before authorization or object-storage invocation

### Requirement: Verified immutable ingestion provenance
The service SHALL expose a file as available only after server-side verification of the stored object and durable creation of immutable ingestion provenance. The record MUST link the upload or multipart session, actor and credential provenance, storage identity, verified object metadata, authorization evidence, request/idempotency correlation, quota settlement, and audit event; it MUST NOT store raw credentials or complete presigned URLs.

#### Scenario: Verified upload becomes available
- **WHEN** a caller completes an authorized upload and the provider object matches declared policy
- **THEN** the service SHALL create immutable ingestion evidence, append lifecycle events, settle quota, record audit information, and expose the resulting file as available

#### Scenario: Object verification fails
- **WHEN** provider metadata, content length, content type, checksum, or object version fails the upload policy
- **THEN** the service SHALL not create an available file and SHALL retain a failed or recoverable ingestion record

### Requirement: Provider-verified multipart completion
The service SHALL verify multipart completion and part metadata from the configured object-storage provider. Client-provided part ETags and lengths are assertions only and MUST NOT by themselves authorize final completion.

#### Scenario: Client supplies forged multipart part data
- **WHEN** the submitted part list differs from provider-visible multipart or resulting object state
- **THEN** the service SHALL reject completion, retain recovery evidence, and SHALL not expose a completed file
