## Purpose

为第三方应用实现不暴露底层 S3 凭证的平台身份和 API Key 生命周期，并将 Key scope、应用角色、目录范围、租户治理及限流共同纳入服务端授权。

## Requirements

### Requirement: 应用身份与 Owner
系统 SHALL 将应用建模为独立 principal，并 SHALL 要求至少一个有效用户或用户组 Owner；Owner 失效时 SHALL 标记应用待接管而非静默删除。

#### Scenario: 最后一个 Owner 被停用
- **WHEN** 应用最后一个有效 Owner 失效
- **THEN** 系统 SHALL 标记应用待接管并通知租户管理员

### Requirement: API Key 安全生命周期
系统 SHALL 使用非秘密 key ID 与高熵 secret，secret 仅显示一次并仅保存验证摘要；系统 SHALL 支持到期、轮换、禁用和吊销。

#### Scenario: 再次读取 secret
- **WHEN** 管理员请求已签发 Key 的原始 secret
- **THEN** 系统 SHALL 拒绝并要求轮换或新建

### Requirement: 权限交集与限流
最终权限 SHALL 是 Key scope、应用 RoleBinding、目录策略、租户治理及操作白名单的交集，并 SHALL 按 Key、应用和租户限流。

#### Scenario: scope 允许但目录不允许
- **WHEN** Key scope 包含上传但应用无目标目录写权限
- **THEN** 系统 SHALL 拒绝上传

### Requirement: 吊销边界
Key 吊销 SHALL 立即阻止新平台请求和新预签名签发，但系统 MUST NOT 承诺已经签发的 URL 在到期前立即失效。

#### Scenario: 吊销前 URL 尚未到期
- **WHEN** Key 被吊销且既有预签名 URL 仍在有效期
- **THEN** 系统 SHALL 保留审计中的最晚到期信息并明确剩余暴露窗口
### Requirement: Application and API Key HTTP lifecycle
The service SHALL expose the declared application, ownership, and API Key lifecycle operations through authorized tenant-scoped HTTP endpoints, including issue, inspect, rotate, revoke, and one-time secret behavior.

#### Scenario: Revoked key secret lookup
- **WHEN** a client requests a secret for an issued, rotated, or revoked API Key after its one-time response
- **THEN** the service SHALL return `410 secret_not_retrievable` and SHALL not return the secret

### Requirement: Application lifecycle service coordination
Application and API Key operations SHALL execute through tenant-scoped application services that enforce ownership, credential status, scope intersection, idempotency, audit recording, and one-time-secret handling before exposing a response.

#### Scenario: API Key is issued
- **WHEN** an authorized principal requests a new API Key for an application it may manage
- **THEN** the lifecycle service SHALL persist only a secret verifier, record a redacted audit event, and return the raw secret only in the issuance response
