## MODIFIED Requirements

### Requirement: Canonical Key 与目录授权
系统 SHALL 对对象 key 执行唯一规范校验并拒绝路径穿越、反斜杠、控制字符和编码歧义；每个文件、上传、下载签名、multipart、删除和对象变更请求 SHALL 在调用对象存储前，以 application principal、其当前租户授权代表 Membership、storage space、canonical relative key、操作和当前 authorization version 进行授权。物理 Bucket 和 key SHALL 仅由服务端将获授权的 relative key 与不可由调用方伪造的 tenant/storage-space namespace 派生，授权与 S3 执行 SHALL 使用同一 Bucket、key 和方法。异步或延迟执行的操作 SHALL 在开始执行前重新确认 application 状态、授权代表 Membership 状态、authorization version、Key scope 及当前资源权限。

#### Scenario: 应用代表拥有写权限
- **WHEN** 应用 API Key scope 和当前租户授权代表均允许 `files.write`，且相对路径落在授予的 storage space/目录范围
- **THEN** 系统 SHALL 生成服务端 namespace 下的物理目标并允许上传

#### Scenario: 授权对象与执行对象不同
- **WHEN** 拟执行的 Bucket、key 或方法与已授权命令不一致
- **THEN** 系统 SHALL 在调用 S3 前拒绝

#### Scenario: 未授权主体访问同租户文件
- **WHEN** 已认证主体对其没有有效 RoleBinding 的文件、前缀、上传会话或 multipart 会话执行操作
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得仅因 tenant_id 匹配而允许

#### Scenario: 应用代表没有写权限
- **WHEN** 应用 API Key scope 允许写入但其授权代表没有目标范围的 `files.write`
- **THEN** 系统 SHALL 返回 `403 permission_denied`，不得调用 S3

#### Scenario: 排队操作在应用代表失效后开始
- **WHEN** 文件操作排队后、执行前，应用授权代表被暂停、移除、到期或其 authorization version 已变化
- **THEN** 系统 SHALL 不执行对象变更，并记录可审计的 `cancelled` 或 `failed` 结果

#### Scenario: 排队操作在成员暂停后开始
- **WHEN** 文件操作排队后、执行前，其人类 acting principal 的 membership 被暂停、移除、到期或其 authorization version 已变化
- **THEN** 系统 SHALL 不执行对象变更，并记录可审计的 `cancelled` 或 `failed` 结果
