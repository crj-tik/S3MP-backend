## Purpose

Provide a reproducible local backend runtime in which PostgreSQL, Redis, and MinIO are configured, verified, and safely usable together without placing credentials in tracked configuration.

## Requirements

### Requirement: Verified local dependency readiness
When the local development API is configured with PostgreSQL, Redis, and MinIO, readiness SHALL report each dependency independently and SHALL not report ready unless every enabled dependency is reachable and authorized.

#### Scenario: MinIO bucket is unavailable
- **WHEN** the API starts with object storage enabled but cannot access the configured development bucket
- **THEN** readiness SHALL return unavailable for object storage without treating database or Redis success as overall readiness

### Requirement: Runtime secret references
The local runtime SHALL obtain database, Redis, and MinIO credentials from environment or secret-file references and SHALL NOT require credential values in tracked Compose, source, logs, or API responses.

#### Scenario: API starts in the backend Compose network
- **WHEN** the API is deployed as a container alongside its local dependencies
- **THEN** it SHALL resolve dependency endpoints through explicitly configured service-network addresses and secret references