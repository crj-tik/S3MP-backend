## MODIFIED Requirements

### Requirement: S3 兼容连接
平台 SHALL 配置唯一 active 的共享 S3 连接，显式包含 endpoint、region、SigV4、path-style、Bucket 和服务端凭据引用；租户级存储接口 MUST NOT 接受任意 Bucket 或 Region。未声明的 AWS S3 能力 SHALL 默认返回 unsupported，AK/SK MUST 仅由服务端秘密来源注入。

#### Scenario: Tenant submits a different bucket
- **WHEN** 租户创建或更新逻辑存储空间并提交与平台配置不同的 Bucket 或 Region
- **THEN** 系统 SHALL 拒绝覆盖并继续使用平台共享配置

#### Scenario: 关键连接配置缺失
- **WHEN** endpoint、region、共享 Bucket、凭据引用或 path-style 配置缺失
- **THEN** 系统 SHALL 快速失败或标记共享连接不可用而不回退默认值

### Requirement: Canonical Key 与目录授权
系统 SHALL 对对象 key 执行唯一规范校验并拒绝路径穿越、反斜杠、控制字符和编码歧义；每个文件、上传、下载签名、multipart、删除和对象变更请求 SHALL 在调用对象存储前，以认证主体、tenant、application namespace、canonical relative key、操作和当前 authorization version 进行授权。物理 Bucket 和 key SHALL 仅由服务端将获授权的 relative key 与不可由调用方伪造的租户/应用 namespace 派生。

#### Scenario: Authorization target differs from execution target
- **WHEN** 拟执行的 Bucket、application namespace、key 或方法与已授权命令不一致
- **THEN** 系统 SHALL 在调用 S3 前拒绝

#### Scenario: Group member accesses an application path
- **WHEN** 用户通过用户组获得某应用 `reports/` 目录的 `files.read`
- **THEN** 系统 SHALL 只返回该应用 `reports/` 下的对象，不得返回其他应用或 `reports2/` 下的对象

#### Scenario: 授权对象与执行对象不同
- **WHEN** 拟执行的 Bucket、Key、应用命名空间或方法与已授权命令不一致
- **THEN** 系统 SHALL 在调用 S3 前拒绝

#### Scenario: 未授权主体访问同租户文件
- **WHEN** 已认证主体对其没有有效 RoleBinding 的应用文件、前缀、上传会话或 multipart 会话执行操作
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得仅因 tenant_id 匹配而允许

#### Scenario: 排队操作在成员暂停后开始
- **WHEN** 文件操作排队后、执行前，其人类 acting principal 的 membership 被暂停、移除、到期或其 authorization version 已变化
- **THEN** 系统 SHALL 不执行对象变更，并记录可审计的 `cancelled` 或 `failed` 结果

### Requirement: Multipart 生命周期
Multipart 会话 SHALL 绑定 tenant、application、主体、逻辑存储空间、canonical key、派生共享 Bucket/physical key、大小、配额 reservation 和到期时间。所有 session、part、完成和中止操作 SHALL 重新验证主体所有权、应用状态、授权和配额；完成 SHALL 校验 provider 上传 ID、part 清单和最终对象元数据。

#### Scenario: Cross-application upload ID is used
- **WHEN** 调用方将某应用的 upload ID 或 part 用于另一个应用
- **THEN** 系统 SHALL 拒绝且不得访问共享 Bucket 中的目标

#### Scenario: 跨会话使用 upload ID
- **WHEN** 调用方将 upload ID 或 part 用于其他主体或其他对象
- **THEN** 系统 SHALL 拒绝并记录安全事件

#### Scenario: Multipart provider 完成结果不匹配
- **WHEN** 对象提供商缺少会话、part ETag 或最终对象元数据与已授权 multipart 命令不一致
- **THEN** 系统 SHALL 不得创建可用文件，并 SHALL 保留失败或隔离状态供重试或清理

## ADDED Requirements

### Requirement: File operation enum filters
文件列表和文件操作查询 SHALL 使用目录中的 file、upload、multipart 和 file-operation 状态枚举；`GET /files` SHALL 支持 `status`，文件操作查询 SHALL 使用强类型状态。服务层 SHALL 校验状态与所属应用命名空间的关联，仓储层 SHALL 执行状态条件并排除软删除或隔离记录。

#### Scenario: File list is filtered by status
- **WHEN** 调用方按目录中的文件状态查询应用内文件
- **THEN** 系统 SHALL 只返回当前应用命名空间内匹配且可用的记录

#### Scenario: Isolated file is queried by status
- **WHEN** 调用方尝试通过状态筛选读取 quarantined 或已删除文件
- **THEN** 系统 SHALL 按文件可见性规则排除该记录，不得因筛选参数绕过隔离

## MODIFIED Requirements

### Requirement: 配额和审计
上传前 SHALL 预留应用和租户容量，完成后 SHALL 按实际对象状态结算；文件、预签名、删除、失败和配额拒绝 SHALL 生成不含凭证或完整 URL 的租户审计，并 SHALL 能按应用聚合使用量。

#### Scenario: Actual size exceeds application quota
- **WHEN** 上传对象实际大小导致应用或租户配额超限
- **THEN** 系统 SHALL 隔离或受控清理对象而不标记可用，并 SHALL 释放或结算 reservation

#### Scenario: 实际大小导致超额
- **WHEN** 上传对象实际大小超过声明并导致配额超限
- **THEN** 系统 SHALL 隔离或受控清理对象而不标记可用
