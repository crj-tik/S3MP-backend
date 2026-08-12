## ADDED Requirements

### Requirement: Authenticated application-service request boundary
Every protected public route SHALL obtain a verified `PrincipalContext` before invoking a tenant-scoped application service. A route MUST reject a request that lacks valid context and MUST NOT silently use a no-op persistence or authorization fallback.

#### Scenario: Protected request lacks authentication context
- **WHEN** a client calls a protected operation without a verified principal context
- **THEN** the service SHALL return `401 authentication_required` before invoking the application operation

#### Scenario: Protected request has valid context
- **WHEN** a client calls a protected operation with valid tenant and principal credentials
- **THEN** the route SHALL delegate the request to the corresponding tenant-scoped application service
