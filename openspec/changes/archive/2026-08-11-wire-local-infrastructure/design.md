## Context

See proposal.md. PostgreSQL and Redis are declared in `deploy/compose.yaml`; MinIO is deployed separately in `local-s3/compose.yaml`. API configuration supports all three, but the backend Compose profile does not pass MinIO settings and Redis is currently only used for readiness.

## Goals / Non-Goals

**Goals:**
- Make local host and Docker-network connection profiles explicit and secret-safe.
- Verify all enabled dependencies before reporting readiness.
- Replace process-local coordination fallbacks with Redis adapters where runtime semantics require durability.

**Non-Goals:**
- Merge the independent MinIO Compose project into the backend production deployment.
- Add production credentials or relax production TLS/secret-file constraints.

## Decisions

### 1. Keep MinIO independent and configure its API contract explicitly

The backend Compose project references the independently deployed MinIO endpoint through environment/secret references. Host execution and container execution receive separate documented endpoint values. This preserves the existing local-S3 lifecycle while avoiding hidden localhost assumptions.

### 2. Model enabled dependencies as readiness participants

PostgreSQL and Redis are mandatory for the configured backend profile. MinIO is mandatory whenever the S3 profile is enabled. A startup migration step runs before API readiness; readiness verifies, but does not mutate, MinIO.

### 3. Redis owns durable coordination state

Use Redis namespaces and bounded TTLs for idempotency replay, rate-limit windows, worker leases, and outbox coordination. In-memory implementations remain test doubles only, because they do not survive process restart.

## Risks / Trade-offs

- [Separate Compose projects have different network scopes] → document host and shared-network endpoint profiles and test both.
- [Automatic migrations can delay startup] → make migration execution explicit, observable, and fail-fast before readiness.
- [Redis persistence policy affects recovery] → enable AOF in local Compose and use database records as the source of truth for business outcomes.

## Migration Plan

1. Add secret-safe development configuration and Compose wiring for the S3 profile.
2. Add Redis adapters and dependency readiness coverage.
3. Run migrations before API readiness, then validate the three dependency checks and restart behavior.
