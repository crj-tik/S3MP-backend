## MODIFIED Requirements

### Requirement: Server-owned provider object namespace
系统 SHALL 从认证主体、租户和应用绑定推导共享 Bucket 及对象 Key。派生 Key SHALL 包含服务端拥有且稳定的租户/应用命名空间后再拼接调用方的 canonical relative key。任何调用方字段、storage space 名称、可变 root prefix 或请求中的 Bucket MUST NOT 选择其他租户或应用的 provider 命名空间。

#### Scenario: Two tenants share one configured bucket
- **WHEN** 两个租户在同一平台共享 Bucket 中提交相同应用内相对 Key
- **THEN** 系统 SHALL 将其解析为不同租户/应用命名空间下的 provider Key

#### Scenario: Application tries another namespace
- **WHEN** 应用提交另一个应用的 namespace 或 physical key
- **THEN** 系统 SHALL 返回 `403 permission_denied` 且不执行 S3 请求

#### Scenario: Two tenants use the same configured bucket
- **WHEN** 两个租户创建逻辑存储空间并指向同一共享 provider bucket
- **THEN** 相同的 canonical relative key SHALL 解析为不同的 provider object keys

#### Scenario: Caller supplies a traversal or ambiguous storage prefix
- **WHEN** 调用方提交非 canonical、重叠或有歧义的 provider prefix
- **THEN** 系统 SHALL 在持久化前以 `422 validation_failed` 拒绝请求

### Requirement: Provider target consistency
每个 provider 操作，包括 head、put、copy、delete、multipart 生命周期和预签名，SHALL 使用授权命令中捕获的共享 Bucket、应用命名空间和 Key。系统 SHALL 拒绝无法证明属于当前 tenant/application namespace 的持久化文件、任务或目标。

#### Scenario: Delayed work refers to a legacy unscoped target
- **WHEN** 排队操作、入库记录或文件记录缺少可证明属于 tenant/application namespace 的目标
- **THEN** 系统 SHALL 隔离或取消它，不得执行 provider mutation，并 SHALL 创建可审计结果

### Requirement: Safe migration of existing object mappings
系统 SHALL 在启用共享应用命名空间前审计现有连接、storage spaces、文件、上传、multipart、入库和待处理操作。无法安全映射到唯一 tenant/application namespace 的记录 SHALL 在明确修复前保持不可变更、不可签名和不可通过文件接口访问。

#### Scenario: Existing mapping conflicts with another tenant or application
- **WHEN** 迁移审计发现同一 provider Key 被多个租户或应用使用
- **THEN** 系统 SHALL 报告冲突并隔离该对象，不得静默保留跨边界访问

#### Scenario: Existing mapping conflicts with another tenant
- **WHEN** 迁移审计识别出 provider bucket/key namespace 被多个 tenant 使用
- **THEN** 系统 SHALL 报告冲突并不得静默保留跨租户 provider access

## ADDED Requirements

### Requirement: Cross-layer enum and lifecycle filtering
所有带枚举筛选的存储、文件和迁移查询 SHALL 在接口层、应用服务层、领域层和持久层使用同一枚举定义；默认 SHALL 过滤软删除、隔离和父级无效记录。任何仅在 API 层声明但未在仓储层执行的筛选 SHALL 视为契约不合格。

#### Scenario: Enum filter is applied at every layer
- **WHEN** 调用方提交一个合法状态筛选并使用游标分页
- **THEN** 系统 SHALL 在服务和仓储查询中保留该筛选，结果 SHALL 不包含其他状态或其他租户/应用的记录

#### Scenario: Filter implementation is missing
- **WHEN** 某列表端点声明了枚举筛选但对应仓储未实现条件
- **THEN** 契约一致性测试 SHALL 失败，发布流程不得通过
