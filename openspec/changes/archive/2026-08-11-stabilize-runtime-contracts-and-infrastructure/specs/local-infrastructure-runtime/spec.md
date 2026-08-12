## ADDED Requirements

### Requirement: Reproducible integrated development profile
The project SHALL provide one documented local development profile that configures PostgreSQL, Redis, MinIO, API migrations, and the backend API together. The profile MUST use environment or secret-file references for credentials and MUST expose explicit health checks for enabled dependencies.

#### Scenario: Developer starts the integrated profile
- **WHEN** a developer starts the documented local runtime profile with its required secrets supplied
- **THEN** migrations SHALL complete before the API is considered ready and readiness SHALL report PostgreSQL, Redis, and MinIO independently

### Requirement: Isolated infrastructure test preflight
Infrastructure-backed tests SHALL use explicit test configuration and MUST verify dependency availability and test-data isolation before executing destructive migration or persistence operations. They MUST NOT silently target an unspecified development database.

#### Scenario: Required test dependency is unavailable
- **WHEN** an infrastructure-backed test dependency cannot be reached
- **THEN** the test command SHALL fail or skip with a clear preflight diagnostic identifying the dependency and configuration source
