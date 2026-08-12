## ADDED Requirements

### Requirement: File mutation preconditions and idempotent retries
All public file mutations that can create, complete, delete, abort, or enqueue an object lifecycle action SHALL enforce their declared `Idempotency-Key` and, where declared, `If-Match` precondition. The same idempotency key SHALL be scoped to tenant, authenticated principal, operation, authorized storage target, and a canonical fingerprint of all semantically relevant request fields.

#### Scenario: Equivalent mutation retry
- **WHEN** an authenticated caller repeats a completed or in-progress mutation with the same idempotency key and equivalent canonical request
- **THEN** the API SHALL return the original stable result without repeating provider side effects

#### Scenario: Conflicting mutation retry
- **WHEN** an authenticated caller reuses an idempotency key with a different target or semantically different mutation payload
- **THEN** the API SHALL return a stable conflict error and SHALL not execute the new mutation

#### Scenario: Stale deletion precondition
- **WHEN** a delete operation supplies an `If-Match` value that does not match the current file version or ETag
- **THEN** the API SHALL return a precondition failure and SHALL not delete the object or database record

### Requirement: Security failures retain the standard error envelope
Authentication, authorization, object verification, and mutation-precondition failures on public file endpoints SHALL return registered stable error codes and the standard error envelope without leaking another tenant's resource existence, physical object key, credentials, or presigned URL.

#### Scenario: Unauthorized multipart access
- **WHEN** an authenticated caller accesses a multipart session owned by another principal or outside its authorized prefix
- **THEN** the API SHALL reject the request with a registered error code and request ID without returning session or provider details
