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

