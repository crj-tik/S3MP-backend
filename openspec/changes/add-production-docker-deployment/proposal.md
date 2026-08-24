## Why

The repository only contains local-integration Compose files: they depend on a
host-local infrastructure topology and do not package the frontend. A Linux
server needs an isolated, reproducible production stack that can be run without
installing Node, Python, nvm, or uv on the host.

## What Changes

- Add a production frontend image that builds the Vue application with Node 22
  and serves its immutable static assets through Nginx.
- Add a production Compose topology for the frontend reverse proxy, API,
  worker, scheduler, PostgreSQL, and Redis, with durable volumes and
  internal-only infrastructure networking; connect it to a pre-provisioned
  online S3-compatible storage service.
- Add an Nginx configuration that provides SPA fallback and proxies `/api/` to
  the API service on the same HTTPS origin.
- Add production environment and secret-file templates plus deployment,
  backup, and verification instructions.

## Capabilities

### New Capabilities

- `production-container-deployment`: A self-contained Linux Docker deployment
  for the S3MP frontend, API, background services, and required local
  infrastructure.

### Modified Capabilities

- None.

## Impact

- Adds deployment files under `deploy/` and a frontend production Dockerfile.
- Requires Docker Engine and Docker Compose on the host; Node, npm, Python,
  nvm, and uv stay inside build/runtime containers.
- Introduces persistent Docker volumes for PostgreSQL and Redis, requires an
  operator-provisioned online S3 Bucket, and requires production secrets to be
  mounted as files rather than committed.
