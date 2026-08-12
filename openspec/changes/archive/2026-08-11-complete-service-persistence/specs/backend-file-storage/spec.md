## ADDED Requirements

### Requirement: Executable MinIO-backed object lifecycle
Development and integration workflows SHALL execute object operations through the configured MinIO-compatible S3 service, verify observed objects before completion, and isolate integration cleanup to a unique test prefix.

#### Scenario: Direct upload completion is claimed
- **WHEN** a client completes a direct upload
- **THEN** the service SHALL verify the object key and observed metadata before making the file available

### Requirement: Quota and multipart settlement
Upload and multipart sessions SHALL reserve quota before accepting storage work and SHALL settle or release it on verified completion, abort, expiry, or recoverable failure.

#### Scenario: Multipart session expires
- **WHEN** a multipart session expires before completion
- **THEN** the system SHALL abort the provider upload where possible and release its reserved quota
