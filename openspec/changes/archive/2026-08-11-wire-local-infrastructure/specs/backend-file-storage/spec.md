## ADDED Requirements

### Requirement: Local MinIO development integration
The development API SHALL use the configured MinIO-compatible endpoint and bucket for object-storage readiness and integration workflows, with path-style addressing and development-only HTTP permitted by explicit configuration.

#### Scenario: API receives the local S3 profile
- **WHEN** the local backend deployment starts
- **THEN** it SHALL receive endpoint, region, path-style, bucket, and credential references required to construct its object-storage adapter
