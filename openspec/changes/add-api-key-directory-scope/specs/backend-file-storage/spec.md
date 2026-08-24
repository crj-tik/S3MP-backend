## MODIFIED Requirements

### Requirement: Canonical Key 与目录授权
系统 SHALL 对对象 key 执行唯一规范校验并拒绝路径穿越、反斜杠、控制字符和编码歧义；每个文件、上传、下载签名、multipart、删除和对象变更请求 SHALL 在调用对象存储前，以目标 storage space、canonical relative key、操作和当前 authorization version 进行授权。应用 API Key 请求的目标应用、storage space、namespace 和 Key 目录范围 SHALL 仅由经认证 Key 推导；应用 API 的调用方输入 SHALL 被解释为相对 Key 目录范围的 key 或前缀，`application_code` SHALL 仅解析同租户 active 操作应用并写入审计，不得改变目标 namespace 或目录范围。浏览器请求 SHALL 以 application_id 选择目标应用并以当前人类主体审计，且不受 API Key 目录范围约束。物理 Bucket 和 key SHALL 仅由服务端将获授权的完整 relative key 与不可由调用方伪造的 tenant/storage-space namespace 派生，授权与 S3 执行 SHALL 使用同一 Bucket、key 和方法。异步或延迟执行的操作 SHALL 在开始执行前重新确认目标应用状态、Key scope、Key 目录范围、操作应用或人类主体状态及当前资源权限。

#### Scenario: Key-relative upload is authorized
- **WHEN** 目录范围为 `contracts/2026` 的应用 API Key 请求写入 `case-a.md`，且 scope、目标应用目录策略和同租户操作应用均有效
- **THEN** 系统 SHALL 对完整 relative key `contracts/2026/case-a.md` 授权，并仅在 API Key 所属目标应用 namespace 下执行上传和记录审计

#### Scenario: 应用代表拥有写权限
- **WHEN** 应用 API Key scope 和当前租户授权代表均允许 `files.write`，且 Key-relative path 派生的完整相对路径落在 Key 目录范围和授予的 storage space/目录范围
- **THEN** 系统 SHALL 生成服务端 namespace 下的物理目标并允许上传

#### Scenario: 应用代表没有写权限
- **WHEN** 应用 API Key scope 允许写入但其授权代表没有由 Key-relative path 派生的目标范围 `files.write`
- **THEN** 系统 SHALL 返回 `403 permission_denied`，不得调用 S3

#### Scenario: 授权对象与执行对象不同
- **WHEN** 拟执行的 Bucket、key 或方法与由 Key 目录范围授权的命令不一致
- **THEN** 系统 SHALL 在调用 S3 前拒绝

#### Scenario: 未授权主体访问同租户文件
- **WHEN** 已认证主体对其没有有效 RoleBinding 的文件、前缀、上传会话或 multipart 会话执行操作
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得仅因 tenant_id 匹配而允许

#### Scenario: 排队操作在成员暂停后开始
- **WHEN** 文件操作排队后、执行前，其人类 acting principal 的 membership 被暂停、移除、到期或其 authorization version 已变化
- **THEN** 系统 SHALL 不执行对象变更，并记录可审计的 `cancelled` 或 `failed` 结果

#### Scenario: 排队操作在应用代表失效后开始
- **WHEN** 文件操作排队后、执行前，应用授权代表被暂停、移除、到期或其 authorization version 已变化
- **THEN** 系统 SHALL 不执行对象变更，并记录可审计的 `cancelled` 或 `failed` 结果

#### Scenario: Key-relative list stays within its boundary
- **WHEN** 目录范围为 `team` 的应用 API Key 列举相对前缀为空或 `reports`
- **THEN** 系统 SHALL 只返回 `team` 或 `team/reports` 下的对象，不得返回 `team2` 或目标应用根目录中的其他对象

#### Scenario: Application API supplies an application-root path
- **WHEN** 目录范围为 `contracts/2026` 的应用 API Key 提交包含该范围之外的完整应用内路径
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得把调用方输入直接用于对象存储

#### Scenario: Deferred operation is revalidated
- **WHEN** 目录受限 Key 创建的上传、multipart 或对象操作在后续阶段执行
- **THEN** 系统 SHALL 复核保存的 Key 目录范围、派生完整 relative key、目标应用、Key scope 和 Key 状态；任何不匹配 SHALL 阻止对象变更
