## ADDED Requirements

### Requirement: Storage-space listing filters remain tenant-bound
The storage-space list SHALL apply an optional application filter only after
enforcing the authenticated tenant boundary and the existing active resource
visibility rules. An application identifier from another tenant, a deleted
application, or an application that is not visible in the current tenant SHALL
produce an empty result set or the established not-found behavior without
revealing cross-tenant records.

#### Scenario: Same application identifier is requested in another tenant
- **WHEN** a caller lists storage spaces with an application identifier owned by another tenant
- **THEN** the response SHALL contain no storage spaces from that application

#### Scenario: Deleted application is used as a filter
- **WHEN** a caller lists storage spaces with an application identifier whose application is not active
- **THEN** the response SHALL contain no active storage spaces for that application
