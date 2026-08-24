## Context

See proposal.md for motivation. The existing Compose files are intentionally
local-integration focused: one expects host-local PostgreSQL, Redis, and MinIO;
the other manages PostgreSQL and Redis but not MinIO. The frontend has a Vite
build but no production image or reverse proxy configuration.

## Goals / Non-Goals

**Goals:**

- Provide a single Linux-oriented Compose topology with persistent services.
- Keep build toolchains inside images: Node 22 for the frontend build and
  Python 3.12 plus uv for backend images.
- Serve the frontend and API on one origin so browser session cookies and CSRF
  requests work without CORS configuration.
- Keep infrastructure ports private by default and require file-mounted
  production secrets.

**Non-Goals:**

- Automated TLS certificate issuance or DNS management.
- Multi-node orchestration, high availability, or managed-cloud provisioning.
- Replacing an existing external PostgreSQL, Redis, or S3 service.

## Decisions

### Separate production Compose file

Add `deploy/compose.production.yaml` rather than changing the local files.
This avoids making Windows local integration depend on production secrets or
changing its host-network assumptions. The topology owns PostgreSQL and Redis
using named volumes and connects to an operator-provisioned online S3 service.

### Multi-stage frontend image with Nginx

The frontend image builds with `node:22` and serves only `dist/` from an Nginx
runtime stage. Nginx performs SPA fallback and proxies `/api/` to `api:8000`.
This removes nvm and Node from the host and is simpler than running Vite in
production. An alternative host-built static bundle was rejected because it
reintroduces a server-side Node lifecycle.

### Docker secrets exposed as read-only files

The API configuration already supports `*_FILE` settings in production. Compose
will mount secret files read-only and set the matching file-reference variables.
This is stronger than literal Compose environment values, although plain Docker
Compose secrets still require operators to protect the source files.

### Explicit database migration job

Migrations run through a one-shot Compose command before long-lived services
are started. This makes schema updates observable and prevents concurrent API
replicas from racing migrations.

## Risks / Trade-offs

- [Single-host volumes are not HA] → Document host-level backups and recovery;
  use managed services or orchestration for HA requirements.
- [Online S3 availability and credentials are external dependencies] → Require
  a pre-created Bucket, least-privilege credentials, and documented endpoint
  settings before startup.
- [HTTPS is environment-specific] → Publish HTTP port binding only as a
  controlled default and document placing a TLS terminator in front of it.

## Migration Plan

1. Install Docker Engine and the Compose plugin on the Linux host.
2. Copy the environment and secret templates outside the repository, set secure
   permissions, and populate production values.
3. Build images, run the one-shot migration command, then start the stack.
4. Verify Compose health and `/api/v1/health/ready` through the reverse proxy.
5. Roll back application images using the prior source revision while retaining
   volumes; do not remove volumes as part of rollback.
