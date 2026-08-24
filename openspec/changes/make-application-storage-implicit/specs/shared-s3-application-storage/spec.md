## MODIFIED Requirements

### Requirement: Platform-owned shared S3 profile
系统 SHALL 使用平台级共享 S3 配置作为所有租户文件操作的唯一存储目标，配置至少包含 endpoint、region、bucket、path-style、签名版本、服务端凭据引用和共享 Bucket 容量 `S3MP_S3_BUCKET_CAPACITY_GIB`。租户和第三方应用 MUST NOT 选择或覆盖这些字段，也 MUST NOT 显式创建、绑定或替换逻辑存储空间。

#### Scenario: Tenant creates application storage
- **WHEN** 平台创建租户或租户创建应用
- **THEN** 系统 SHALL 从当前 active 共享配置自动建立内部存储上下文，不接受或要求存储目标输入

#### Scenario: Shared profile is unavailable
- **WHEN** 平台没有可用的 active 共享 S3 配置
- **THEN** 租户或应用存储初始化、文件、上传、预签名和探测操作 SHALL 失败并返回稳定的存储配置错误，不得回退到调用方提交的目标

#### Scenario: Bucket capacity is configured in GiB
- **WHEN** 平台启动并加载共享 S3 配置
- **THEN** 系统 SHALL 将 `S3MP_S3_BUCKET_CAPACITY_GIB` 精确转换为内部 bytes，并以该值限制租户总配额

## ADDED Requirements

### Requirement: Storage space is not a public application resource
内部 storage-space 标识 MAY 在迁移期用于持久化和路由，但公开应用管理体验 SHALL 仅暴露派生的只读存储摘要，不得提供创建、绑定、解绑或选择操作。

#### Scenario: Application UI loads storage information
- **WHEN** 应用界面加载存储信息
- **THEN** 系统 SHALL 以该应用自动拥有的唯一存储摘要响应，不要求前端查询候选空间列表
