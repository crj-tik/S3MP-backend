## MODIFIED Requirements

### Requirement: Canonical Key 与目录授权
系统 SHALL 对对象 key 执行唯一规范校验并拒绝路径穿越、反斜杠、控制字符和编码歧义；每个文件、上传、下载签名、multipart、删除和对象变更请求 SHALL 在调用对象存储前，以认证主体、storage space、canonical relative key、操作和当前 authorization version 进行授权。物理 Bucket 和 key SHALL 仅由服务端将获授权的 relative key 与不可由调用方伪造的 tenant/storage-space namespace 派生，授权与 S3 执行 SHALL 使用同一 Bucket、key 和方法。异步或延迟执行的操作 SHALL 在开始执行前重新确认主体状态、有效 membership（人类主体）、authorization version、Key scope（如适用）及当前资源权限。

#### Scenario: 授权对象与执行对象不同
- **WHEN** 拟执行的 Bucket、key 或方法与已授权命令不一致
- **THEN** 系统 SHALL 在调用 S3 前拒绝

#### Scenario: 未授权主体访问同租户文件
- **WHEN** 已认证主体对其没有有效 RoleBinding 的文件、前缀、上传会话或 multipart 会话执行操作
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得仅因 tenant_id 匹配而允许

#### Scenario: 排队操作在成员暂停后开始
- **WHEN** 文件操作排队后、执行前，其人类 acting principal 的 membership 被暂停、移除、到期或其 authorization version 已变化
- **THEN** 系统 SHALL 不执行对象变更，并记录可审计的 `cancelled` 或 `failed` 结果

### Requirement: 文件列举与预签名
系统 SHALL 在授权范围内列举和读取元数据，并仅为精确、已存在且属于指定 storage space 的 private 对象签发短时 PUT/GET URL；调用方 SHALL 提供 canonical relative key 而非物理 Bucket key，完整 URL MUST NOT 被持久化或记录。文件列举 SHALL 使用 canonical directory-boundary 语义：某目录前缀只匹配该前缀本身及以该前缀加 `/` 开始的对象，不得因普通字符串前缀匹配泄露相似目录。客户端声明直传完成时，系统 SHALL 使用 HeadObject 校验派生 key、实际大小、类型及摘要要求后才标记可用。

#### Scenario: 确认直传完成
- **WHEN** 客户端声明 PUT 直传完成
- **THEN** 系统 SHALL 使用 HeadObject 校验 key、实际大小、类型及摘要要求后才标记可用

#### Scenario: 请求任意物理对象的下载签名
- **WHEN** 调用方提交不属于已授权 storage space 的 physical key、不存在的对象或未被授予读取权限的 relative key
- **THEN** 系统 SHALL 拒绝签发 URL，且不得把调用方输入直接传递给对象存储签名接口

#### Scenario: 列举相似但无权的目录
- **WHEN** 调用方仅对 `team` 目录拥有 `files.list`，但同一 storage space 存在 `team2` 目录
- **THEN** 列举 `team` SHALL 不返回 `team2` 中的对象或元数据

### Requirement: Executable file and governance lifecycle API
The service SHALL expose contract-declared storage, file, upload, multipart, object-operation, quota, and audit operations through authenticated tenant-scoped HTTP endpoints while preserving authorization, object-state, quota, and audit requirements. Every operation with a declared permission SHALL enforce that permission before its application service performs a read or mutation; API Key credentials SHALL be rejected from management operations before handler execution.

#### Scenario: Management operation is requested without its declared permission
- **WHEN** an authenticated caller invokes a storage, quota, or audit operation without the operation's declared permission
- **THEN** the service SHALL return `403 permission_denied` without invoking the application operation

#### Scenario: API Key calls a management operation
- **WHEN** a caller using an API Key requests a storage-management, quota-management, audit, identity, authorization, application, or API-Key management operation
- **THEN** the service SHALL return `403 permission_denied` before the handler executes

#### Scenario: High-risk file operation cannot be audited
- **WHEN** a high-risk object mutation or signature issuance cannot durably record its audit event
- **THEN** the service SHALL reject the operation with `503 audit_unavailable` before reporting success

### Requirement: Coordinated object lifecycle services
File query, upload, multipart, object-operation, quota, and audit use cases SHALL execute through application services that use tenant-scoped persistence and object-storage ports. They SHALL persist operation intent before external storage work and SHALL record completed, failed, or partial-failure outcomes after verification. A file-operation result SHALL be visible only to its creator or to a caller that currently has explicit delegated authorization for every affected storage-space path; public responses SHALL exclude tenant identifiers, principal identifiers, idempotency values, leases, provider credentials, and authorization evidence.

#### Scenario: Source deletion fails after a verified move copy
- **WHEN** a move operation verifies its destination object but cannot delete the source
- **THEN** the object-operation service SHALL persist and return a recoverable `partial_failure` outcome rather than report complete success

#### Scenario: Same-tenant caller queries another principal's operation
- **WHEN** an authenticated caller requests a file operation created by a different principal without current delegated authorization for its affected paths
- **THEN** the service SHALL return `403 permission_denied` without returning operation metadata
