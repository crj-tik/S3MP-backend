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
