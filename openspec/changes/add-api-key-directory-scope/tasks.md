## 1. Key directory-scope domain and contract

- [x] 1.1 Add canonical optional `directory_prefix` support to the API Key domain model, persistence schema and migration; backfill existing Keys as root-scoped.
- [x] 1.2 Extend API Key issue, inspect, list and rotation DTOs/OpenAPI schemas with a non-secret directory-scope summary and validate all supplied directory prefixes.
- [x] 1.3 Implement logical directory establishment for a non-root Key scope, including a reserved-marker strategy only when required by existing directory browsing, with compensation on issuance failure.
- [x] 1.4 Add backend lifecycle tests for root scope, child scope, invalid prefixes, persistence, secret redaction and rollback-safe legacy Keys.

## 2. Application API path and authorization enforcement

- [x] 2.1 Add a centralized Key-scope path resolver that canonicalizes Key-relative object keys and list prefixes, composes the complete application-relative key and enforces directory-boundary semantics.
- [x] 2.2 Wire the resolver into every application API file query, direct upload, download/signature, delete, copy/move and list endpoint before metadata or object-store access.
- [x] 2.3 Preserve browser `application_id` data-plane routes as application-root-relative and ensure they do not apply an API Key directory scope.
- [x] 2.4 Keep API Key target application and `application_code` audit actor separate while propagating the Key ID, directory prefix and resolved complete key into authorization evidence and audits.
- [x] 2.5 Add route-matrix tests proving root scopes work, child scopes cannot reach parent/sibling/similar prefixes, invalid actor codes are rejected, and browser routes remain unchanged.

## 3. Durable uploads, multipart, pre-signing and asynchronous work

- [x] 3.1 Persist Key ID, directory-prefix evidence and complete application-relative key on direct-upload, multipart, pre-sign and file-operation records as needed for continuation safety.
- [x] 3.2 Revalidate stored Key scope, target application, Key lifecycle and derived object key on direct-upload completion, multipart part/list/complete/abort, download signing and object-operation retries.
- [x] 3.3 Ensure provider calls, HeadObject checks, file listing and quota accounting use only the server-derived complete key and filter any technical directory marker from user-visible files and usage.
- [x] 3.4 Add integration tests for continuation/session-ID boundary escapes, revoked restricted Keys, prefix collision (`team` versus `team2`), and no provider call on denial.

## 4. Frontend API Key management

- [x] 4.1 Regenerate frontend API client types from the updated OpenAPI contract after backend endpoints are complete.
- [x] 4.2 Add an optional “存取目录” input to API Key creation with clear root-directory default, canonical-path guidance and backend validation feedback.
- [x] 4.3 Show the configured directory scope in API Key lists/details without exposing any secret or physical storage namespace.
- [x] 4.4 Add frontend tests for root default, directory submission, response rendering and validation errors.

## 5. Verification and rollout

- [x] 5.1 Run backend unit, HTTP, migration and object-storage integration tests plus OpenAPI generation/contract checks.
- [x] 5.2 Run frontend typecheck, lint, API-client generation and tests.
- [x] 5.3 Verify an end-to-end cross-application audit case: the Key targets its configured application directory while same-tenant `application_code` is recorded solely as the actor.
