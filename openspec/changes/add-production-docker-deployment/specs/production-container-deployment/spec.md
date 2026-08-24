## Purpose

Provide a repeatable production deployment that runs the S3MP web interface,
API, background services, and required infrastructure on a Linux Docker host.

## ADDED Requirements

### Requirement: Self-contained production stack
The system SHALL provide a production Compose topology that starts the frontend,
API, file worker, platform scheduler, PostgreSQL, and Redis, and SHALL connect
to a pre-provisioned online S3-compatible object storage service without
requiring Node, npm, Python, nvm, or uv on the host.

#### Scenario: Start on a prepared Linux Docker host
- **WHEN** an operator provides the required production environment and secret files and starts the production Compose stack
- **THEN** all application services, PostgreSQL, and Redis start from container images, local state is retained in named persistent volumes, and the application connects to the configured external S3 service

### Requirement: Same-origin browser access
The production frontend SHALL be served through a reverse proxy that provides
SPA history fallback and forwards `/api/` requests to the API service over the
internal Compose network.

#### Scenario: Refresh a deep application route
- **WHEN** a user refreshes a browser route that is not a physical static asset
- **THEN** the reverse proxy returns the frontend application entry point instead of a 404 response

### Requirement: Production secret handling
The production deployment SHALL load database, Redis, S3, and API-key-pepper
secrets from mounted files and SHALL not require secrets to be committed to the
repository or baked into application images.

#### Scenario: Production configuration validation
- **WHEN** the production stack starts with secret file references configured
- **THEN** the API loads its required credentials from those files and can complete its readiness checks without exposing their values in configuration templates

### Requirement: Operable initialization and verification
The deployment documentation SHALL define database migration, readiness check,
backup, and rollback commands usable from the Docker host.

#### Scenario: First production deployment
- **WHEN** an operator follows the documented initialization sequence
- **THEN** migrations run before write traffic is enabled and the operator can verify API readiness and persistent-service health
