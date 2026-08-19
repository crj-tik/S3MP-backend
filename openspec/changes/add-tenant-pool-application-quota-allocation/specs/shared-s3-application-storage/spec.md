## MODIFIED Requirements

### Requirement: Platform-owned shared S3 profile
系统 SHALL 使用平台级共享 S3 配置作为所有租户文件操作的唯一存储目标，配置至少包含 endpoint、region、bucket、path-style、签名版本、服务端凭据引用和可分配容量上限。租户和第三方应用 MUST NOT 选择或覆盖这些字段。

#### Scenario: Tenant quota is bounded by shared bucket
- **WHEN** 平台管理员设置租户总配额
- **THEN** 系统 SHALL 将其与共享 profile 的可分配容量上限比较，超过上限时拒绝配置

#### Scenario: Tenant creates application storage
- **WHEN** 租户或应用请求创建逻辑存储空间
- **THEN** 系统 SHALL 使用当前 active 的平台共享配置，不接受请求中的 Bucket、Region 或 Endpoint 覆盖值

#### Scenario: Shared profile is unavailable
- **WHEN** 平台没有可用的 active 共享 S3 配置
- **THEN** 文件、上传、预签名和探测操作 SHALL 失败并返回稳定的存储配置错误，不得回退到租户提交的目标

### Requirement: Application-owned storage namespace
每个 active 应用 SHALL 拥有一个租户内唯一且稳定的逻辑存储命名空间。命名空间 SHALL 绑定 tenant_id 和 application_id，并 SHALL 在应用生命周期内保持稳定；应用重命名不得隐式改变已存在对象的物理 Key；该命名空间 SHALL 作为应用独立用量和共享池用量统计的归属边界。

#### Scenario: Application namespace is derived
- **WHEN** 应用请求访问相对路径 `reports/2026.xlsx`
- **THEN** 系统 SHALL 从认证主体和数据库绑定推导该应用命名空间，再生成完整对象目标并将对象计入该应用或共享池

#### Scenario: Cross-application identifier is supplied
- **WHEN** 应用 API Key 请求另一个应用的 storage space 或 namespace
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得访问、探测或计入目标对象

### Requirement: Application namespace lifecycle
应用被暂停、删除或其所属租户被暂停/删除后，系统 SHALL 立即阻止该命名空间的新文件操作、API Key 使用、预签名签发和配额预留；已有对象 SHALL 按平台保留策略保留，不得因状态变更自动改写物理 Key。

#### Scenario: Deleted application quota is excluded
- **WHEN** 已删除应用仍有历史对象或配额记录
- **THEN** 系统 SHALL 将其排除在有效配额和共享池分配计算之外，并通过审计/对账结果暴露该历史状态

#### Scenario: Deleted application key is used
- **WHEN** 已删除应用的 API Key 请求上传、下载、列举或删除
- **THEN** 系统 SHALL 拒绝请求并不得访问共享 Bucket
