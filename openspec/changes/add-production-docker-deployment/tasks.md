## 1. Container artifacts

- [x] 1.1 Add a Node 22 multi-stage frontend Dockerfile that emits an Nginx static-runtime image.
- [x] 1.2 Add Nginx SPA fallback and same-origin API reverse-proxy configuration.

## 2. Production topology

- [x] 2.1 Add a production Compose file for frontend, API, worker, scheduler, PostgreSQL, and Redis with persistent volumes and private service networking.
- [x] 2.2 Add production environment and mounted-secret templates without literal credentials.
- [x] 2.3 Configure the production topology to use a pre-provisioned online S3 Bucket and least-privilege application credentials.

## 3. Operations documentation and verification

- [x] 3.1 Document Linux host prerequisites, initial deployment, migrations, readiness verification, backup, and rollback.
- [x] 3.2 Validate Compose configuration and build the frontend production image.
