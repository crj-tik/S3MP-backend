## MODIFIED Requirements

### Requirement: 契约一致性
系统 SHALL 自动比较运行时 OpenAPI 与 `contracts/openapi.yaml`，SHALL 双向检查（运行时比基线多报错，基线比运行时多也报错），并 SHALL 为契约示例和权限目录提供校验。该比较 SHALL 覆盖每个公开操作的成功响应 JSON schema、必填字段、嵌套结构、分页、`additionalProperties` 与请求/响应媒体类型，而不只覆盖路径、方法和状态码。

#### Scenario: 实现与契约不一致（运行时缺少基线端点）
- **WHEN** CI 检测到基线定义了端点但运行时未实现
- **THEN** 系统 SHALL 使检查失败并阻止无审阅的漂移

#### Scenario: 实现与契约不一致（运行时多出基线端点）
- **WHEN** CI 检测到运行时 Schema、路径或响应与契约基线不一致
- **THEN** 系统 SHALL 使检查失败并阻止无审阅的漂移

#### Scenario: 成功响应字段漂移
- **WHEN** 公开操作的运行时成功响应缺少契约必填字段、暴露未声明字段，或与契约嵌套结构不一致
- **THEN** 契约校验 SHALL 失败并标识该操作与响应状态

### Requirement: Executable public API baseline
Every OpenAPI operation declared in the backend-owned contract SHALL be executable through the runtime application and SHALL preserve its declared path, method, required parameters, response status, success response schema, and stable error envelope. A route MUST NOT be considered executable solely because it is registered when its production dependency graph cannot process an authenticated request.

#### Scenario: Frontend invokes a declared API Key list operation
- **WHEN** a client calls `GET /applications/{application_id}/api_keys` with a valid tenant context
- **THEN** the runtime route SHALL serve that exact path and SHALL NOT require or expose an alternate global API-key list path

#### Scenario: 管理端点在真实生命周期中执行
- **WHEN** 客户端向已启动且连接数据库的应用调用已声明的身份或授权管理操作
- **THEN** 该操作 SHALL 由真实应用服务返回声明的成功响应或已注册的业务错误，而不得因未装配依赖返回 500
