## MODIFIED Requirements

### Requirement: Canonical Key 与目录授权
系统 SHALL 对对象 key 执行唯一规范校验并拒绝路径穿越、反斜杠、控制字符和编码歧义；每个文件、上传、下载签名、multipart、删除和对象变更请求 SHALL 在调用对象存储前，以目标 storage space、canonical relative key、操作和当前 authorization version 进行授权。应用 API Key 请求的目标应用、storage space 和 namespace SHALL 仅由 API Key 绑定的应用推导；请求 `application_code` SHALL 仅解析同租户 active 操作应用并写入审计，不得改变目标 namespace。浏览器请求 SHALL 以 application_id 选择目标应用，并以当前人类主体审计。物理 Bucket 和 key SHALL 仅由服务端将获授权的 relative key 与不可由调用方伪造的 tenant/storage-space namespace 派生，授权与 S3 执行 SHALL 使用同一 Bucket、key 和方法。异步或延迟执行的操作 SHALL 在开始执行前重新确认目标应用状态、Key scope、操作应用或人类主体状态及当前资源权限。

#### Scenario: Other application acts using a target application's key
- **WHEN** 应用 API Key scope 允许 `files.write`，请求 code 解析为同租户 active 操作应用，且相对路径合法
- **THEN** 系统 SHALL 在 API Key 所属目标应用命名空间生成物理目标并允许上传，且审计记录操作应用和目标应用

#### Scenario: 应用代表拥有写权限
- **WHEN** 应用 API Key scope 允许 `files.write`，目标应用可用，且请求 code 解析为同租户 active 操作应用
- **THEN** 系统 SHALL 生成 API Key 所属目标应用 namespace 下的物理目标并允许上传

#### Scenario: 应用代表没有写权限
- **WHEN** 应用 API Key scope 不允许 `files.write` 或目标应用目录策略拒绝写入
- **THEN** 系统 SHALL 返回 `403 permission_denied`，不得调用 S3

#### Scenario: Audit actor code is invalid
- **WHEN** 应用 API 请求的 application_code 不存在、已失效或不属于 API Key 所属租户
- **THEN** 系统 SHALL 返回拒绝结果，且不得调用 S3 或通过错误信息泄露跨租户应用信息

#### Scenario: 浏览器主体拥有写权限
- **WHEN** 当前浏览器用户拥有 application_id 所属目标范围的 `files.write`，且相对路径落在授予的 storage space/目录范围
- **THEN** 系统 SHALL 生成服务端 namespace 下的物理目标并允许上传，并将用户记录为操作主体

#### Scenario: 授权对象与执行对象不同
- **WHEN** 拟执行的 Bucket、key 或方法与已授权命令不一致
- **THEN** 系统 SHALL 在调用 S3 前拒绝

#### Scenario: 未授权主体访问同租户文件
- **WHEN** 已认证主体对其没有有效权限的文件、前缀、上传会话或 multipart 会话执行操作
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得仅因 tenant_id 匹配而允许

#### Scenario: 排队操作在操作主体失效后开始
- **WHEN** 文件操作排队后、执行前，其操作应用已失效，或人类 acting principal 的 membership 被暂停、移除、到期或其 authorization version 已变化
- **THEN** 系统 SHALL 不执行对象变更，并记录可审计的 `cancelled` 或 `failed` 结果

#### Scenario: 排队操作在成员暂停后开始
- **WHEN** 浏览器文件操作排队后、执行前，其人类 acting principal 的 membership 被暂停、移除、到期或其 authorization version 已变化
- **THEN** 系统 SHALL 不执行对象变更，并记录可审计的 `cancelled` 或 `failed` 结果

#### Scenario: 排队操作在目标应用或 Key 失效后开始
- **WHEN** 文件操作排队后、执行前，目标应用、其 API Key 或其 authorization version 已失效
- **THEN** 系统 SHALL 不执行对象变更，并记录可审计的 `cancelled` 或 `failed` 结果

#### Scenario: 排队操作在应用代表失效后开始
- **WHEN** 应用文件操作排队后、执行前，目标应用、其 API Key 或请求 code 对应的操作应用已失效
- **THEN** 系统 SHALL 不执行对象变更，并记录可审计的 `cancelled` 或 `failed` 结果
