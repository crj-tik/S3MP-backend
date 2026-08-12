## Purpose

实现受租户和目录授权保护的文件数据面，并封装公司 S3 协议子集、预签名、multipart、对象变更状态机、配额及审计，使调用方获得稳定且可验证的文件服务行为。

## Requirements

### Requirement: S3 兼容连接
每个存储连接 SHALL 显式配置 endpoint、region、SigV4 和 path-style；未声明的 AWS S3 能力 SHALL 默认返回 unsupported，AK/SK MUST 仅由服务端秘密来源注入。

#### Scenario: 关键连接配置缺失
- **WHEN** endpoint、region、凭证引用或 path-style 配置缺失
- **THEN** 系统 SHALL 快速失败或标记连接不可用而不回退默认值

### Requirement: Canonical Key 与目录授权
系统 SHALL 对对象 key 执行唯一规范校验并拒绝路径穿越、反斜杠、控制字符和编码歧义；授权与 S3 执行 SHALL 使用相同 Bucket、key 和方法。

#### Scenario: 授权对象与执行对象不同
- **WHEN** 拟执行的 Bucket、key 或方法与 AuthorizedCommand 不一致
- **THEN** 系统 SHALL 在调用 S3 前拒绝

### Requirement: 文件列举与预签名
系统 SHALL 在授权范围内列举和读取元数据，并仅为精确 private 对象签发短时 PUT/GET URL；完整 URL MUST NOT 被持久化或记录。

#### Scenario: 确认直传完成
- **WHEN** 客户端声明 PUT 直传完成
- **THEN** 系统 SHALL 使用 HeadObject 校验 key、实际大小、类型及摘要要求后才标记可用

### Requirement: Multipart 生命周期
Multipart 会话 SHALL 绑定租户、主体、storage space、canonical key、大小、配额和到期时间，并支持完成校验及过期 Abort。

#### Scenario: 跨会话使用 upload ID
- **WHEN** 调用方将 upload ID 或 part 用于其他主体或对象
- **THEN** 系统 SHALL 拒绝并记录安全事件

### Requirement: 对象变更状态机
复制 SHALL 校验源读和目标写；移动还 SHALL 校验源删除，并在复制验证后删除源。部分失败 MUST NOT 报告完整成功。

#### Scenario: 移动删源失败
- **WHEN** 目标复制验证成功但源删除失败
- **THEN** 系统 SHALL 保存可恢复的部分失败状态

### Requirement: 配额和审计
上传前 SHALL 预留容量，完成后 SHALL 按实际对象状态结算；文件、预签名、删除和失败 SHALL 生成不含凭证或完整 URL 的租户审计。

#### Scenario: 实际大小导致超额
- **WHEN** 上传对象实际大小超过声明并导致配额超限
- **THEN** 系统 SHALL 隔离或受控清理对象而不标记可用
### Requirement: Executable file and governance lifecycle API
The service SHALL expose contract-declared storage, file, upload, multipart, object-operation, quota, and audit operations through tenant-scoped HTTP endpoints while preserving authorization, object-state, quota, and audit requirements.

#### Scenario: High-risk file operation cannot be audited
- **WHEN** a high-risk object mutation or signature issuance cannot durably record its audit event
- **THEN** the service SHALL reject the operation with `503 audit_unavailable` before reporting success

### Requirement: Coordinated object lifecycle services
File query, upload, multipart, object-operation, quota, and audit use cases SHALL execute through application services that use tenant-scoped persistence and object-storage ports. They SHALL persist operation intent before external storage work and SHALL record completed, failed, or partial-failure outcomes after verification.

#### Scenario: Source deletion fails after a verified move copy
- **WHEN** a move operation verifies its destination object but cannot delete the source
- **THEN** the object-operation service SHALL persist and return a recoverable `partial_failure` outcome rather than report complete success
