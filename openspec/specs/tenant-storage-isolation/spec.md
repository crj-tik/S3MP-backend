# tenant-storage-isolation Specification

## Purpose

Ensure every provider-side object target is uniquely and verifiably owned by one tenant and one storage space, even when all tenants share a MinIO endpoint and bucket.

## Requirements

### Requirement: Server-owned provider object namespace
The system SHALL derive the provider bucket and object key exclusively from a storage space that belongs to the authenticated tenant. The derived object key SHALL contain a server-owned, canonical tenant and storage-space namespace before the caller-controlled relative key. No caller-supplied field, storage-space name, or mutable root-prefix value SHALL select another tenant's provider object namespace.

#### Scenario: Two tenants use the same configured bucket
- **WHEN** two tenants create storage spaces that target the same provider bucket
- **THEN** an identical canonical relative key in the two spaces SHALL resolve to distinct provider object keys

#### Scenario: Caller supplies a traversal or ambiguous storage prefix
- **WHEN** a caller creates or updates a storage space with a non-canonical, overlapping, or ambiguous provider prefix
- **THEN** the system SHALL reject the request with `422 validation_failed` before persisting the space

### Requirement: Provider target consistency
Every provider operation, including head, put, copy, delete, multipart lifecycle, and presigning, SHALL use the bucket and key captured in the authorized command. The system SHALL reject an operation when the persisted file or task target cannot be proven to be within the current storage space's derived namespace.

#### Scenario: Delayed work refers to a legacy unscoped target
- **WHEN** a queued operation, ingestion record, or file record lacks a target that can be proven to belong to its tenant and storage space
- **THEN** the system SHALL quarantine or cancel it without performing a provider mutation and SHALL create an auditable outcome

### Requirement: Safe migration of existing object mappings
The system SHALL provide a migration audit for existing storage spaces, file records, uploads, multipart sessions, ingestion records, and pending operations before enabling the namespaced target format. Records that cannot be safely mapped SHALL remain unavailable for provider mutation until explicitly remediated.

#### Scenario: Existing mapping conflicts with another tenant
- **WHEN** migration audit identifies a provider bucket/key namespace used by more than one tenant
- **THEN** the system SHALL report the conflict and SHALL not silently retain cross-tenant provider access
