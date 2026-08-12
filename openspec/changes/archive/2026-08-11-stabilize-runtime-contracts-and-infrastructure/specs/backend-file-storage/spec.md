## ADDED Requirements

### Requirement: Executable S3-backed file lifecycle
The service SHALL perform declared upload, download, multipart, copy, move, and delete workflows against the configured object-storage connection. It MUST verify the relevant object state before exposing a completed result and SHALL not substitute placeholder URLs or database-only completion for an enabled storage connection.

#### Scenario: Upload completion is verified
- **WHEN** a caller completes an upload to an enabled storage space
- **THEN** the service SHALL verify the stored object and persist its verified metadata before returning an available file

#### Scenario: Multipart upload is completed
- **WHEN** a caller completes a valid multipart upload
- **THEN** the service SHALL complete the corresponding object-storage multipart session, verify the resulting object, and settle the associated file state

### Requirement: File lifecycle settlement and recovery
File mutations SHALL reserve and settle quota, record redacted audit information, and persist enough operation state to recover from storage or persistence failure. A verified copy followed by a failed source deletion MUST be reported as a recoverable partial failure rather than complete success.

#### Scenario: Move source deletion fails
- **WHEN** the destination copy is verified but the source object cannot be deleted
- **THEN** the service SHALL persist and return a `partial_failure` operation outcome with recovery information
