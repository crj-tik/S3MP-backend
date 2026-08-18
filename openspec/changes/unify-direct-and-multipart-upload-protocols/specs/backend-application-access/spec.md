## ADDED Requirements

### Requirement: 应用凭证统一授权两种上传模式
应用 API Key 的有效权限 SHALL 同时受应用状态、storage space、canonical relative key、目录 RoleBinding、Key scope、配额和 authorization version 约束。直传会话签发和 Multipart 会话/分片操作 SHALL 使用同一套应用边界校验；获得 presigned URL 不得绕过完成确认或目录授权。应用不得提交 tenant_id、bucket、physical key 或 provider upload ID 作为授权边界。

#### Scenario: 直传 URL 只能写入授权对象
- **WHEN** 应用为有权的 relative key 请求直传 URL
- **THEN** 系统 SHALL 只为服务端派生的目标对象签发短期 URL，并 SHALL 记录授权依据

#### Scenario: Multipart 分片不能越权
- **WHEN** 应用使用属于其他空间、其他应用或其他主体的 multipart ID 上传分片
- **THEN** 系统 SHALL 返回稳定的认证或授权错误，不得调用 provider

#### Scenario: Key 被吊销后完成上传
- **WHEN** API Key 在直传 URL 签发后被吊销，应用仍调用 S3MP 完成接口
- **THEN** 系统 SHALL 按既定延迟主体校验策略拒绝不再满足授权的提交，并 SHALL 不创建可用文件
