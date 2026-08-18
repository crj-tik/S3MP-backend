## Purpose

定义由后端兑现并维护的版本化接口契约，使前端能够只读生成类型、客户端与 Mock，同时确保错误、分页、权限和状态机语义不会在两个实施对话之间漂移。
## Requirements
### Requirement: 版本化契约基线
系统 SHALL 在 `contracts/**` 提供 `/api/v1` OpenAPI、API 约定、错误码、权限操作目录和示例，且 SHALL 在实现接口前先更新契约。

#### Scenario: 后端新增接口
- **WHEN** 后端准备新增或改变可观察 API 行为
- **THEN** 系统 SHALL 先更新契约并通过兼容性检查，再实现和发布接口

### Requirement: 稳定通用协议
JSON 字段 SHALL 使用 snake_case，时间 SHALL 使用 UTC RFC 3339，分页 SHALL 使用绑定租户、主体和查询条件的不透明 cursor，错误 SHALL 返回 code、message、request_id 和可选 details。

#### Scenario: 业务校验失败
- **WHEN** 请求不满足业务校验
- **THEN** 系统 SHALL 返回稳定机器错误码和 request_id，不要求调用方解析 message

### Requirement: 当前用户上下文
系统 SHALL 提供 `/api/v1/me`，返回当前用户、当前及可选租户、粗粒度权限集合和 authorization version。

#### Scenario: 有效会话查询上下文
- **WHEN** ACTIVE 用户使用有效会话请求 `/api/v1/me`
- **THEN** 系统 SHALL 返回其服务端推导的当前租户和最新权限版本

### Requirement: 契约一致性
系统 SHALL 自动比较运行时 OpenAPI 与 `contracts/openapi.yaml`，SHALL 双向检查（运行时比基线多报错，基线比运行时多也报错），并 SHALL 为契约示例和权限目录提供校验。

#### Scenario: 实现与契约不一致（运行时缺少基线端点）
- **WHEN** CI 检测到基线定义了端点但运行时未实现
- **THEN** 系统 SHALL 使检查失败并阻止无审阅的漂移

#### Scenario: 实现与契约不一致（运行时多出基线端点）
- **WHEN** CI 检测到运行时 Schema、路径或响应与契约基线不一致
- **THEN** 系统 SHALL 使检查失败并阻止无审阅的漂移

### Requirement: Executable public API baseline
Every OpenAPI operation declared in the backend-owned contract SHALL be executable through the runtime application and SHALL preserve its declared path, method, required parameters, response status, and stable error envelope.

#### Scenario: Frontend invokes a declared API Key list operation
- **WHEN** a client calls `GET /applications/{application_id}/api_keys` with a valid tenant context
- **THEN** the runtime route SHALL serve that exact path and SHALL NOT require or expose an alternate global API-key list path

### Requirement: Contract-aligned error vocabulary
The runtime service SHALL emit only error codes registered in the backend error catalog for public API failures.

#### Scenario: Authentication is missing or unusable
- **WHEN** a protected operation has no valid authentication context
- **THEN** the service SHALL return `401 authentication_required`

### Requirement: File mutation preconditions and idempotent retries
All public file mutations that can create, complete, delete, abort, or enqueue an object lifecycle action SHALL enforce their declared `Idempotency-Key` and, where declared, `If-Match` precondition. The same idempotency key SHALL be scoped to tenant, authenticated principal, operation, authorized storage target, and a canonical fingerprint of all semantically relevant request fields.

#### Scenario: Equivalent mutation retry
- **WHEN** an authenticated caller repeats a completed or in-progress mutation with the same idempotency key and equivalent canonical request
- **THEN** the API SHALL return the original stable result without repeating provider side effects

#### Scenario: Conflicting mutation retry
- **WHEN** an authenticated caller reuses an idempotency key with a different target or semantically different mutation payload
- **THEN** the API SHALL return a stable conflict error and SHALL not execute the new mutation

#### Scenario: Stale deletion precondition
- **WHEN** a delete operation supplies an `If-Match` value that does not match the current file version or ETag
- **THEN** the API SHALL return a precondition failure and SHALL not delete the object or database record

### Requirement: Security failures retain the standard error envelope
Authentication, authorization, object verification, and mutation-precondition failures on public file endpoints SHALL return registered stable error codes and the standard error envelope without leaking another tenant's resource existence, physical object key, credentials, or presigned URL.

#### Scenario: Unauthorized multipart access
- **WHEN** an authenticated caller accesses a multipart session owned by another principal or outside its authorized prefix
- **THEN** the API SHALL reject the request with a registered error code and request ID without returning session or provider details

### Requirement: Authentication and platform APIs are contract-declared
The service SHALL declare login, logout, account context, tenant-session
selection, and platform tenant lifecycle operations in the published contract
before exposing them at runtime. The contract SHALL distinguish public account
authentication from account-session, tenant-session, and platform authorization.

#### Scenario: Frontend performs browser login
- **WHEN** the frontend calls the declared login operation with a supported credential payload
- **THEN** the runtime SHALL provide the declared status, cookie behavior, and stable error envelope

### Requirement: Platform account registration and identifier login are published
The runtime service and checked-in contract SHALL describe global account registration, email or company employee-number login, account and tenant CSRF cookies, and the `X-S3MP-CSRF` header with identical semantics. Account control-plane mutations SHALL use `s3mp_account_csrf`; tenant-scoped mutations SHALL use `s3mp_csrf`, including when both sessions exist.

#### Scenario: Frontend reads account authentication contract
- **WHEN** the frontend loads Swagger or `contracts/openapi.yaml`
- **THEN** it SHALL know that login sets `s3mp_account_session` and `s3mp_account_csrf`, logout and tenant selection require the account CSRF value in `X-S3MP-CSRF`, and tenant APIs use `s3mp_csrf`

#### Scenario: Tenant mutation with both browser sessions
- **WHEN** a browser has both `s3mp_account_session` and `s3mp_session` and sends a tenant-scoped mutation
- **THEN** the server SHALL validate `X-S3MP-CSRF` against `s3mp_csrf` and SHALL accept the request when they match

#### Scenario: Account mutation with both browser sessions
- **WHEN** a browser has both sessions and sends an account control-plane mutation
- **THEN** the server SHALL validate `X-S3MP-CSRF` against `s3mp_account_csrf`

### Requirement: Contract documentation remains synchronized with Swagger
The published `contracts/openapi.yaml` and runtime Swagger schema SHALL contain the same Chinese operation, parameter, request-field, and response-field descriptions for every public operation.

#### Scenario: Contract documentation is validated
- **WHEN** CI validates the runtime schema against the published OpenAPI contract
- **THEN** it SHALL reject missing or divergent required Chinese documentation metadata

### Requirement: CSRF documentation matches the enforced security domain
The runtime and published contract SHALL explain that account control-plane mutations use `s3mp_account_csrf`, while tenant-scoped mutations use `s3mp_csrf`. This rule SHALL remain valid when both account and tenant session cookies are present.

#### Scenario: Tenant mutation after tenant selection
- **WHEN** a browser has both `s3mp_account_session` and `s3mp_session` and sends a tenant-scoped mutation
- **THEN** the server SHALL validate `X-S3MP-CSRF` against `s3mp_csrf` and SHALL accept the request when they match

#### Scenario: Account mutation after tenant selection
- **WHEN** a browser has both sessions and sends an account control-plane mutation
- **THEN** the server SHALL validate `X-S3MP-CSRF` against `s3mp_account_csrf`

### Requirement: Platform control-plane management APIs are contract-declared
The service SHALL publish stable, documented, cursor-paginated API operations
for authorized platform account discovery, platform role and role-binding
inspection, Support Access request inspection, and platform audit inspection.
Each operation SHALL declare its required platform permission, request filters,
response DTOs, pagination behavior, and standard error envelope in the runtime
OpenAPI document and checked-in contract before release.

#### Scenario: Frontend renders the platform support queue
- **WHEN** the frontend reads the published OpenAPI contract
- **THEN** it SHALL find a documented paginated operation for listing Support Access requests with stable request identifiers and status fields required for approval or revocation

#### Scenario: Platform authorization is missing
- **WHEN** a caller invokes a platform control-plane management operation without the operation's required platform permission
- **THEN** the API SHALL return the standard authorization error envelope and SHALL not return any platform or tenant resource record

### Requirement: Platform and storage response schemas are explicit
The runtime application and checked-in OpenAPI contract SHALL declare explicit
response schemas for platform tenant list/detail/update operations, platform
role-binding and Support Access list operations, and storage connection probe
results. These operations MUST NOT expose `unknown` responses or reuse a
request-body schema as a semantically different response. The probe response
SHALL describe status, read/write capability, check time, and safe failure
information without exposing credentials or signing material.

#### Scenario: Contract exposes platform tenant resources
- **WHEN** the frontend generates types from the contract
- **THEN** tenant list, detail, and update operations SHALL resolve to `PlatformTenantPage` or `PlatformTenantResponse`, not `unknown` or `TenantUpdate`

#### Scenario: Contract exposes probe results
- **WHEN** the frontend invokes a storage connection probe
- **THEN** the response SHALL resolve to a dedicated probe-result schema and SHALL not resolve to the probe request body

### Requirement: Platform list contracts perform filter-stable cursor pagination
Every platform or tenant-scoped list contract, including tenants, platform roles,
storage spaces, role bindings, and platform audit events, SHALL accept bounded
cursor pagination and return only the records matching all supplied filters in
its `items` collection. The storage-space list SHALL support `application_id`,
the role-binding list SHALL support `storage_space_id`, and the platform audit
list SHALL support `resource_type` and `resource_id` in addition to its existing
filters. A cursor SHALL be valid only for the operation and normalized filter
set for which it was issued. Lifecycle-status query parameters SHALL accept only
the documented values and reject unsupported values as a validation error.

#### Scenario: Application filtered storage page
- **WHEN** an authorized caller requests storage spaces with an `application_id`
- **THEN** the API SHALL return only active, visible storage spaces belonging to that application and current tenant

#### Scenario: Storage-space filtered role-binding page
- **WHEN** an authorized caller requests role bindings with a `storage_space_id`
- **THEN** the API SHALL return only bindings whose scope references that storage space within the current tenant

#### Scenario: Resource filtered platform audit page
- **WHEN** an authorized platform operator requests audit events with `resource_type` and `resource_id`
- **THEN** the API SHALL return only events matching both resource filters

#### Scenario: Filtered support page has later matches
- **WHEN** more than `limit` earlier records do not match the requested filters and matching records exist after them
- **THEN** the returned page SHALL contain the earliest matching records and SHALL provide a next cursor whenever further matching records exist

#### Scenario: Caller reuses a cursor with different filters
- **WHEN** a caller presents an opaque list cursor with a different query or lifecycle filter from the request that issued it
- **THEN** the API SHALL reject the cursor and SHALL not mix records from distinct result sets

### Requirement: Support Access responses identify safe approval subjects
An authorized Support Access list or detail response SHALL include a safe
approver account summary when the request has been approved, in addition to
the existing approver identifier. The summary SHALL use the same safe account
fields as requester summaries and SHALL omit credentials, sessions, and
tenant-scoped permissions.

#### Scenario: Operator reviews an approved request
- **WHEN** an authorized operator retrieves an approved Support Access request
- **THEN** the response SHALL include both the requester summary and the safe approver summary
