## MODIFIED Requirements

### Requirement: 应用身份与 Owner
系统 SHALL 将每个 application 建模为独立、已启用的 application principal，并 SHALL 要求至少一个有效用户或用户组 Owner。Owner 失效时 SHALL 标记应用待接管而非静默删除。既有 application 的迁移 SHALL 建立独立主体，且不得把创建者的 human principal 作为 application principal 复用。

#### Scenario: 最后一个 Owner 被停用
- **WHEN** 应用最后一个有效 Owner 失效
- **THEN** 系统 SHALL 标记应用待接管并通知租户管理员

#### Scenario: 既有应用完成主体迁移
- **WHEN** 系统迁移一个已有 application
- **THEN** 该 application SHALL 关联一个同租户、类型为 application 的独立 principal，且原 Owner 的 human principal 不得被当作应用主体

### Requirement: 权限交集与限流
最终权限 SHALL 是 Key scope、application principal 的 RoleBinding、目录策略、租户治理及操作白名单的交集，并 SHALL 按 Key、应用和租户限流。API Key SHALL 仅用于被明确允许的机器调用端点，且不得用于身份、授权、application 或 API-Key 管理端点。

#### Scenario: scope 允许但目录不允许
- **WHEN** Key scope 包含上传但 application 无目标目录写权限
- **THEN** 系统 SHALL 拒绝上传

#### Scenario: API Key 访问管理端点
- **WHEN** 调用方使用 API Key 请求身份、授权、application 或 API-Key 管理端点
- **THEN** 系统 SHALL 返回 `403 permission_denied` 且不得执行管理操作

### Requirement: Application and API Key HTTP lifecycle
服务 SHALL 通过已授权且租户范围内的 HTTP 端点公开 application、ownership 和 API Key 生命周期操作，包括签发、查看、轮换、吊销及一次性 secret 行为。每个管理操作 SHALL 同时在 HTTP 边界和服务边界验证调用者对目标 application 的管理权限或有效 Owner 关系。

#### Scenario: Revoked key secret lookup
- **WHEN** 客户端请求已签发、轮换或吊销 API Key 的原始 secret
- **THEN** 服务 SHALL 返回 `410 secret_not_retrievable` 且不得返回 secret

#### Scenario: 无权主体管理其他应用的 Key
- **WHEN** 已认证主体尝试为其无管理权限且非 Owner 的 application 签发、轮换或吊销 API Key
- **THEN** 服务 SHALL 返回 `403 permission_denied` 且不得改变目标 Key

### Requirement: Application lifecycle service coordination
Application 和 API Key 操作 SHALL 通过租户范围的应用服务执行，并在暴露响应前实施 ownership、credential status、scope intersection、幂等性、审计记录和一次性 secret 处理。认证 API Key 时，服务 SHALL 同时确认 Key、所属 application 和 application principal 都处于可用状态，并只以该 principal 构造机器主体上下文。

#### Scenario: API Key is issued
- **WHEN** 有权主体为其可管理的 application 请求新 API Key
- **THEN** 生命周期服务 SHALL 仅持久化 secret verifier，记录脱敏审计事件，并只在签发响应中返回原始 secret

#### Scenario: 已停用应用使用有效 Key
- **WHEN** 一个未过期且未吊销的 API Key 所属 application 或 application principal 已停用
- **THEN** 服务 SHALL 返回 `401 authentication_required` 且不得构造主体上下文
