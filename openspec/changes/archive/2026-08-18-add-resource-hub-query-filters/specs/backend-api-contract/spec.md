## MODIFIED Requirements

### Requirement: Platform list contracts perform filter-stable cursor pagination
Every platform or tenant-scoped list contract, including tenants, platform roles,
storage spaces, role bindings, and platform audit events, SHALL accept bounded
cursor pagination and return only the records matching all supplied filters in
its `items` collection. The storage-space list SHALL support `application_id`,
the role-binding list SHALL support `storage_space_id`, and the platform audit
list SHALL support `resource_type` and `resource_id` in addition to its existing
filters. A cursor SHALL be valid only for the operation and normalized filter
set for which it was issued. Lifecycle-status query parameters SHALL accept only
the documented values and reject unsupported values as a validation error.

#### Scenario: Application filtered storage page
- **WHEN** an authorized caller requests storage spaces with an `application_id`
- **THEN** the API SHALL return only active, visible storage spaces belonging to that application and current tenant

#### Scenario: Storage-space filtered role-binding page
- **WHEN** an authorized caller requests role bindings with a `storage_space_id`
- **THEN** the API SHALL return only bindings whose scope references that storage space within the current tenant

#### Scenario: Resource filtered platform audit page
- **WHEN** an authorized platform operator requests audit events with `resource_type` and `resource_id`
- **THEN** the API SHALL return only events matching both resource filters

#### Scenario: Filtered support page has later matches
- **WHEN** more than `limit` earlier records do not match the requested filters and matching records exist after them
- **THEN** the returned page SHALL contain the earliest matching records and SHALL provide a next cursor whenever further matching records exist

#### Scenario: Caller reuses a cursor with different filters
- **WHEN** a caller presents an opaque list cursor with a different query or lifecycle filter from the request that issued it
- **THEN** the API SHALL reject the cursor and SHALL not mix records from distinct result sets
