## MODIFIED Requirements

### Requirement: Platform-owned shared S3 profile

系统 SHALL 使用平台级共享 S3 配置作为所有租户文件操作的唯一存储目标，配置至少包含 endpoint、region、bucket、path-style、签名版本、服务端凭据引用和共享 Bucket 容量 `S3MP_S3_BUCKET_CAPACITY_GIB`。租户和第三方应用 MUST NOT 选择或覆盖这些字段。

#### Scenario: Tenant creates application storage

- **WHEN** 租户或应用请求创建逻辑存储空间
- **THEN** 系统 SHALL 使用当前 active 的平台共享配置，不接受请求中的 Bucket、Region 或 Endpoint 覆盖值

#### Scenario: Shared profile is unavailable

- **WHEN** 平台没有可用的 active 共享 S3 配置
- **THEN** 文件、上传、预签名和探测操作 SHALL 失败并返回稳定的存储配置错误，不得回退到租户提交的目标

#### Scenario: Bucket capacity is configured in GiB

- **WHEN** 平台启动并加载共享 S3 配置
- **THEN** 系统 SHALL 将 `S3MP_S3_BUCKET_CAPACITY_GIB` 精确转换为内部 bytes，并以该值限制租户总配额

### Requirement: Application-owned storage namespace

每个 active 应用 SHALL 拥有一个租户内唯一且稳定的逻辑存储命名空间。命名空间 SHALL 绑定 tenant_id 和 application_id，并 SHALL 在应用生命周期内保持稳定；应用重命名不得隐式改变已存在对象的物理 Key。

#### Scenario: Application namespace is derived

- **WHEN** 应用请求访问相对路径 `reports/2026.xlsx`
- **THEN** 系统 SHALL 从认证主体和数据库绑定推导该应用命名空间，再生成完整对象目标

#### Scenario: Cross-application identifier is supplied

- **WHEN** 应用 API Key 请求另一个应用的 storage space 或 namespace
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得访问或探测目标对象

### Requirement: Server-derived shared-bucket object key

系统 SHALL 将物理对象 Key 推导为稳定的租户/应用命名空间加规范化应用内相对路径。调用方 MUST NOT 提交完整物理 Key、Bucket、租户前缀或其他应用前缀来选择 provider 目标。

#### Scenario: Same relative key in two applications

- **WHEN** 两个租户或两个应用都提交 `data/a.json`
- **THEN** 系统 SHALL 将其解析为互不相同的物理 Key

#### Scenario: Prefix traversal is attempted

- **WHEN** 相对路径包含 `/` 开头、空段、`.`、`..`、反斜杠、百分号编码歧义或控制字符
- **THEN** 系统 SHALL 在任何 S3 调用前返回 `422 validation_failed`

### Requirement: Application namespace lifecycle

应用被暂停、删除或其所属租户被暂停/删除后，系统 SHALL 立即阻止该命名空间的新文件操作、API Key 使用和预签名签发；已有对象 SHALL 按平台保留策略保留，不得因状态变更自动改写物理 Key。

#### Scenario: Deleted application key is used

- **WHEN** 已删除应用的 API Key 请求上传、下载、列举或删除
- **THEN** 系统 SHALL 拒绝请求并不得访问共享 Bucket

### Requirement: Shared storage enum metadata

系统 SHALL 在 `GET /api/v1/metadata/catalog` 中发布共享存储相关的稳定枚举元数据，包括 storage connection、storage space、文件操作类型和共享 profile 的寻址方式。每个枚举项 SHALL 包含稳定 value、中文 label、description、terminal 标识和允许的 transitions；接口不得返回凭据或租户实例数据。

#### Scenario: Frontend renders storage state options

- **WHEN** 前端读取元数据目录
- **THEN** 前端 SHALL 使用目录中的 value、label 和 transitions 渲染存储状态筛选与操作，不得手写后端状态字符串

#### Scenario: Runtime catalog and contract are compared

- **WHEN** 服务端生成 OpenAPI 契约或返回元数据目录
- **THEN** 两者 SHALL 使用同一服务端枚举定义，状态 value 不得出现集合分叉

### Requirement: Storage and lifecycle enum filters

存储和生命周期列表接口 SHALL 使用目录中的租户、应用、API Key、存储空间和存储连接状态枚举；应用、API Key、storage space 与 storage connection 列表 SHALL 支持 `status` 筛选。筛选 SHALL 在服务层验证父级租户/应用状态，并在持久层执行真实条件。

#### Scenario: Storage list is filtered by status

- **WHEN** 管理员按目录中的 `status` 查询应用或存储资源
- **THEN** 系统 SHALL 返回匹配状态且未软删除、父级状态有效的资源，不得返回已删除父级下的孤儿记录

#### Scenario: Caller submits a status not in the catalog

- **WHEN** 请求携带未知 storage 或 lifecycle status
- **THEN** 系统 SHALL 返回 `422 validation_failed`，不得执行无条件列表查询
