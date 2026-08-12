## MODIFIED Requirements

### Requirement: Canonical Key 与目录授权
系统 SHALL 对对象 key 执行唯一规范校验并拒绝路径穿越、反斜杠、控制字符和编码歧义；每个文件、上传、下载签名、multipart、删除和对象变更请求 SHALL 在调用对象存储前，以认证主体、storage space、canonical relative key、操作和当前 authorization version 进行授权。物理 Bucket key SHALL 仅由服务端将获授权的 relative key 与 storage space root prefix 派生，授权与 S3 执行 SHALL 使用相同 Bucket、key 和方法。

#### Scenario: 授权对象与执行对象不同
- **WHEN** 拟执行的 Bucket、key 或方法与已授权命令不一致
- **THEN** 系统 SHALL 在调用 S3 前拒绝

#### Scenario: 未授权主体访问同租户文件
- **WHEN** 已认证主体对其没有有效 RoleBinding 的文件、前缀、上传会话或 multipart 会话执行操作
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得仅因 tenant_id 匹配而允许

### Requirement: 文件列举与预签名
系统 SHALL 在授权范围内列举和读取元数据，并仅为精确、已存在且属于指定 storage space 的 private 对象签发短时 PUT/GET URL；调用方 SHALL 提供 canonical relative key 而非物理 Bucket key，完整 URL MUST NOT 被持久化或记录。客户端声明直传完成时，系统 SHALL 使用 HeadObject 校验派生 key、实际大小、类型及摘要要求后才标记可用。

#### Scenario: 确认直传完成
- **WHEN** 客户端声明 PUT 直传完成
- **THEN** 系统 SHALL 使用 HeadObject 校验 key、实际大小、类型及摘要要求后才标记可用

#### Scenario: 请求任意物理对象的下载签名
- **WHEN** 调用方提交不属于已授权 storage space 的 physical key、不存在的对象或未被授予读取权限的 relative key
- **THEN** 系统 SHALL 拒绝签发 URL，且不得把调用方输入直接传递给对象存储签名接口

### Requirement: Multipart 生命周期
Multipart 会话 SHALL 绑定租户、主体、storage space、canonical key、派生 physical key、大小、配额和到期时间，并使用对象提供商的 create-part-list-complete-abort 生命周期。所有 session、part、完成和中止操作 SHALL 重新验证主体所有权及授权；完成 SHALL 校验 provider 上传 ID、part 编号/ETag 清单和最终对象元数据，过期会话 SHALL Abort。

#### Scenario: 跨会话使用 upload ID
- **WHEN** 调用方将 upload ID 或 part 用于其他主体或对象
- **THEN** 系统 SHALL 拒绝并记录安全事件

#### Scenario: Multipart provider 完成结果不匹配
- **WHEN** 对象提供商缺少会话、part ETag 或最终对象元数据与已授权 multipart 命令不一致
- **THEN** 系统 SHALL 不得创建可用文件，并 SHALL 保留失败或隔离状态供重试或清理
