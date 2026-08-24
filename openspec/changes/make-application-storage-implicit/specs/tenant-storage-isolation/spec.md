## ADDED Requirements

### Requirement: Tenant and application determine the provider namespace
每个 provider 目标 SHALL 由认证租户的默认根和目标应用 ID 唯一确定。调用方 MUST NOT 通过 storage-space ID、名称或候选列表改变租户或应用命名空间。

#### Scenario: Caller addresses an application file
- **WHEN** 调用方在当前租户的应用上下文提交相对对象路径
- **THEN** 服务端 SHALL 解析该应用唯一内部存储记录并生成 `<tenant_slug>/<application_id>/<relative_key>`

