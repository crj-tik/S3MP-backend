## MODIFIED Requirements

### Requirement: 文件列举与预签名
系统 SHALL 在授权范围内列举和读取元数据，并仅为精确、已存在且属于指定 storage space 的 private 对象签发短时 PUT/GET URL；调用方 SHALL 提供 canonical relative key 而非物理 Bucket key，完整 URL MUST NOT 被持久化或记录。上传写入 SHALL 仅通过两种公开模式完成：直传会话签发短时 presigned PUT URL，或由 S3MP 接收真实二进制分片并执行 provider multipart 生命周期。系统 SHALL NOT 暴露完整文件代理上传接口，也 SHALL NOT 通过布尔开关宣称未返回 URL 的直传能力。文件列举 SHALL 使用 canonical directory-boundary 语义：某目录前缀只匹配该前缀本身及以该前缀加 `/` 开始的对象，不得因普通字符串前缀匹配泄露相似目录。客户端声明直传完成时，系统 SHALL 使用 HeadObject 校验派生 key、实际大小、类型及摘要要求后才标记可用。

#### Scenario: 创建直传会话
- **WHEN** 已授权应用为 canonical relative key 创建直传会话
- **THEN** 系统 SHALL 返回带会话标识、过期时间、上传方法、短期 presigned PUT URL 及必要请求头的明确响应，并 SHALL 不返回底层凭证或物理命名空间给应用

#### Scenario: 确认直传完成
- **WHEN** 客户端使用直传 URL 写入对象并调用完成接口
- **THEN** 系统 SHALL 使用 HeadObject 校验 key、实际大小、类型及摘要要求后才标记可用

#### Scenario: 请求代理上传接口
- **WHEN** 客户端调用已删除的完整文件代理上传路径
- **THEN** 运行时 SHALL 不提供该路径，契约 SHALL 不声明该路径或 operationId

#### Scenario: 请求任意物理对象的下载签名
- **WHEN** 调用方提交不属于已授权 storage space 的 physical key、不存在的对象或未被授予读取权限的 relative key
- **THEN** 系统 SHALL 拒绝签发 URL，且不得把调用方输入直接传递给对象存储签名接口

#### Scenario: 列举相似但无权的目录
- **WHEN** 调用方仅对 `team` 目录拥有 `files.list`，但同一 storage space 存在 `team2` 目录
- **THEN** 列举 `team` SHALL 不返回 `team2` 中的对象或元数据

### Requirement: Multipart 生命周期
Multipart 会话 SHALL 绑定租户、主体、storage space、canonical key、派生 physical key、大小、配额和到期时间，并使用对象提供商的 create、真实二进制 part upload、list、complete、abort 生命周期。上传分片接口 SHALL 接收分片二进制并由服务端调用 provider `upload_part`，保存真实 ETag 和长度；系统 SHALL NOT 要求客户端先登记一个空分片再通过另一个接口伪造确认。所有 session、part、完成和中止操作 SHALL 重新验证主体所有权及授权；完成 SHALL 校验 provider 上传 ID、part 编号/ETag 清单和最终对象元数据，过期会话 SHALL Abort。

#### Scenario: 上传真实分片
- **WHEN** 已授权应用向 `/multipart_uploads/{id}/parts/{part_number}` 发送分片二进制
- **THEN** 系统 SHALL 校验会话、主体、分片编号和长度，调用 provider 上传该分片，保存 provider 返回的真实 ETag，并返回分片结果

#### Scenario: 跨会话使用 upload ID
- **WHEN** 调用方将 upload ID 或 part 用于其他主体或对象
- **THEN** 系统 SHALL 拒绝并记录安全事件

#### Scenario: Multipart provider 完成结果不匹配
- **WHEN** 对象提供商缺少会话、part ETag 或最终对象元数据与已授权 multipart 命令不一致
- **THEN** 系统 SHALL 不得创建可用文件，并 SHALL 保留失败或隔离状态供重试或清理

#### Scenario: 调用旧的空分片登记接口
- **WHEN** 客户端调用只登记 part_number 或只确认客户端提交 ETag 的旧接口
- **THEN** 运行时 SHALL 不提供这些路径，契约 SHALL 不声明对应 operationId 或请求 schema

## REMOVED Requirements

### Requirement: 完整文件代理上传
**Reason**: 代理上传与直传、Multipart 形成重复的第三种应用协议，且不符合平台只允许直传和分片上传的设计。
**Migration**: 小文件改用直传会话和 presigned PUT；大文件改用 Multipart 会话及真实二进制分片接口。
