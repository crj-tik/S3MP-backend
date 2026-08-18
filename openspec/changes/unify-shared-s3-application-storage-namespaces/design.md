## Context

当前 `StorageConnection` 和 `StorageSpace` 允许按租户保存 endpoint、region、bucket 和 root prefix；文件命令再根据 tenant/storage space 派生 provider target。授权层已经支持用户、用户组、应用 principal、storage space 和 canonical prefix，但应用与 storage space 还没有强绑定，配额也需要和上传预留及实际入库统一。

本设计将现有 storage space 保留为兼容的逻辑资源名，但把它收敛为“一个应用的逻辑存储命名空间”，并将真实 S3 目标提升为平台共享配置。

## Goals / Non-Goals

**Goals:**

- 使用一个平台共享 S3 连接、Bucket 和 Region 服务所有租户。
- 形成 `tenant namespace / application namespace / relative key` 的稳定 Key 推导链。
- 让浏览器用户、用户组和应用 API Key 使用不同认证方式，但进入同一套应用路径授权判定。
- 支持租户和应用的容量配额、并发 reservation、实际结算和重算。
- 让同步文件操作、上传、multipart、预签名和 worker 使用同一个授权命令与目标推导器。
- 对现有租户级 storage 配置进行可审计迁移，冲突记录默认隔离。

**Non-Goals:**

- 不为用户组增加登录、密码、会话或独立 API Key。
- 不让第三方应用直接获得 AWS/MinIO AK/SK。
- 不在本 change 中实现跨平台多 Bucket 路由或按租户选择区域。
- 不因应用改名自动移动历史对象；命名空间必须稳定。

## Decisions

### 1. 平台单例共享 S3 配置

新增平台级 storage profile，保存 endpoint、region、bucket、path_style、signature_version、credential_reference 和状态。应用服务在启动和每次 provider 操作前解析当前 active profile；租户 API 不再接收可覆盖的 bucket/region/endpoint。

选择单例 profile 而不是保留租户 connection：生产负责人明确只有一个共享 Bucket/Region；保留租户可写连接会使同一逻辑应用可能落到不同物理边界，难以证明隔离。旧 connection 表保留只读迁移信息，完成迁移后不再作为新请求的 provider 选择来源。

### 2. StorageSpace 与 Application 一对一绑定

为 storage space 增加 `application_id`，并以 `(tenant_id, application_id)` 保持唯一。由应用创建或平台/租户管理员显式初始化对应 storage space；space 的 bucket/connection 字段迁移为派生展示字段或兼容只读字段。

应用命名空间使用创建时分配的稳定 `storage_namespace`。默认展示形式为 `tenant_slug/application_slug`，但物理 namespace 一旦分配不得因名称修改而变化；这样既满足可读路径，也避免重命名造成历史对象迁移或路径劫持。数据库中同时保存 tenant_id、application_id 和 namespace，任何请求都以 UUID 归属校验为准，不能仅凭 slug 查找。

### 3. 统一 Key 推导器

所有 provider target 只能由以下输入产生：

```text
authenticated subject
  -> tenant_id
  -> application_id
  -> active application storage namespace
  -> canonical relative key
```

推导结果为：

```text
bucket = active_platform_storage_profile.bucket
key    = storage_namespace + "/" + relative_key
```

客户端不再传 bucket、完整 key 或 tenant prefix。应用 API Key 的 application_id 必须与请求的 storage space/application_id 一致；浏览器用户则必须通过 tenant session 和 RoleBinding 对该应用路径获得权限。物理 key、bucket、签名 URL 和凭据不写入公开响应。

### 4. 用户组作为授权主体，不作为认证主体

用户组继续使用现有 group principal 和 group_member。用户登录后，授权解析器收集用户直接绑定及其 active 用户组 principal 的 RoleBinding；应用 API Key 只解析 application principal 的绑定，不继承普通用户的组成员关系。

RoleBinding 的资源范围由 `application/storage_space_id + canonical_prefix` 表示。绑定到应用根目录的权限覆盖该应用 namespace 下的相对路径；绑定到 `reports/` 只覆盖应用内 `reports/`，目录匹配采用边界语义。deny 优先，组成员变化推进相关授权版本并撤销/重新验证旧会话和排队任务。

选择“组是授权主体”而不是“组是路径目录”：组成员关系会变化，若把组编码进物理 Key，会把身份管理和数据迁移耦合；使用 RoleBinding 可以让同一个组安全地访问多个应用或多个应用内目录。

### 5. 双层配额与 reservation

保留租户聚合配额，并新增应用级配额。数据库维护：

```text
quota_limit
used_bytes
reserved_bytes
updated_at
```

创建 upload/multipart session 时，在事务内锁定租户和应用配额行，同时检查：

```text
used_bytes + reserved_bytes + declared_size <= limit
```

成功完成时以 HeadObject/CompleteMultipart 的实际大小结算；失败、取消、过期释放 reservation；实际大小超过剩余额度时将对象隔离或受控删除。定时 reconciliation 扫描已登记文件和受控 provider listing，报告无法映射的孤儿对象，不自动把不明对象计入应用用量。

### 6. 统一延迟任务证据

上传会话、multipart、ingestion、file operation 和 worker payload 保存 `tenant_id`、`application_id`、storage space、namespace、relative_key、physical_key、authorization_version 和 reservation identity。worker 执行前重新检查应用/租户状态、主体或 API Key scope、授权版本及 reservation，禁止使用旧的客户端 key 或旧 storage profile 重新拼接目标。

### 7. 统一枚举与状态元数据目录

新增只读接口 `GET /api/v1/metadata/catalog`，返回不包含凭据、租户数据或用户隐私的稳定元数据。目录至少包含用户、成员、租户、应用、API Key、上传、分片上传、文件操作、支持访问、存储连接、存储空间等状态，以及授权范围类型、授权效果、文件操作类型和配额范围。

每个状态项 SHALL 提供 `value`、稳定的中文 `label`、`description`、`terminal` 和 `transitions`。前端使用 `value` 进行请求和判断，使用 `label` 与 `description` 展示，使用 `transitions` 决定状态操作按钮；不得复制一套字符串枚举到前端。

该目录 SHALL 版本化、只读、幂等，且不要求 CSRF；它可以在未选择租户前读取，因为返回内容是平台元数据，不包含租户实例数据。权限详细说明继续由 `GET /api/v1/permission_catalog` 提供，平台角色继续由 `GET /api/v1/platform/roles` 提供，避免把动态授权数据与静态枚举混淆。

OpenAPI 与运行时目录 SHALL 使用同一服务端枚举定义生成，防止契约和目录的 value 集合分叉。

枚举的使用链路必须贯穿四层：领域层定义 `StrEnum`、接口层将查询参数声明为对应枚举、应用服务层接收枚举并校验状态与父级生命周期、仓储层将枚举转换为 SQL 条件。任何一层不得退化为不受约束的 `str`，也不得在服务层接收后丢弃筛选条件。

`GET /api/v1/metadata/catalog` 的每个目录项 SHALL 额外声明 `domain`、`resource`、`field`、`query_parameter` 和 `used_by`。允许前端使用目录驱动筛选的业务域包括：`identity`、`lifecycle`、`authorization`、`storage`、`file`、`ingestion`、`quota`、`governance`。未携带 domain 时返回全部公开域；携带重复 `domains` 时按并集返回；未知 domain 返回 `422 validation_failed`。

列表接口的枚举筛选契约固定为：`/users` 支持 `status`、`principal_type`；`/members` 支持 `status`；`/applications`、`/api_keys`、`/storage_spaces`、`/storage_connections`、`/files` 支持 `status`；`/quotas` 支持 `scope`、`status`；`/audit_events` 支持 `event_type`、`severity`；`/platform/tenants` 与 `/platform/support-access` 支持 `status`；入库记录支持 `status`，入库事件支持 `event_type`。不适用的列表接口不得虚构筛选字段。

仓储查询必须同时应用枚举筛选、稳定游标排序、默认软删除过滤以及当前 tenant/application 边界；父级租户或应用处于非活动状态时，子资源不得作为有效业务数据返回。OpenAPI 参数枚举、运行时目录、领域枚举和仓储支持字段必须由一致性测试校验。

## Risks / Trade-offs

- [旧对象没有唯一应用归属] → 迁移前执行 tenant/application/key 审计；无法唯一映射的对象进入 quarantine，不能通过文件 API 或签名 URL 暴露。
- [共享 Bucket 的错误前缀会造成跨租户泄露] → provider target 只接受服务端派生 namespace；所有操作在 S3 调用前复用同一个授权命令，并增加跨租户/跨应用对抗测试。
- [应用重命名导致用户期待路径变化] → 将 storage namespace 设为不可变；显示名可变但对象路径不变，并在 API 返回 display name 与 immutable namespace 的区别。
- [并发上传突破配额] → reservation 与配额检查放入同一数据库事务，完成/失败/过期使用幂等结算事件。
- [旧客户端仍提交 bucket/root_prefix] → 先以兼容读取方式接受但忽略或校验旧字段，返回弃用提示；完成迁移后从 OpenAPI 请求体移除可变 provider 字段。
- [共享配置轮换影响正在进行的上传] → 上传会话保存 provider profile version；轮换期间旧版本只允许完成已有会话，不允许新建会话，并保留受控回滚窗口。

## Migration Plan

1. 创建共享 platform storage profile，校验 endpoint、region、path-style、Bucket 和凭据；执行幂等 Bucket 可用性检查。
2. 为每个 active application 创建唯一稳定 namespace，并将现有 storage space 映射到 application；没有唯一应用归属的 space 标记为 quarantine。
3. 审计 file object、upload、multipart、ingestion、file operation、quota 和 pending worker，验证其物理 Key 能唯一映射到新的 namespace。
4. 对能安全映射的记录写入 application_id、namespace 和 provider profile version；冲突或旧根目录重叠记录只读隔离并生成审计事件。
5. 部署双读/单写阶段：读旧记录仅用于迁移报告，新建记录只写共享 profile 和应用 namespace；worker 同时拒绝无新证据的旧任务。
6. 完成用量重算、配额 reservation 校正和跨租户/跨应用对抗测试后，切换所有文件接口和预签名接口到新推导器。
7. 观察期后移除租户可写的 Bucket/Region/Endpoint 字段和旧 provider target 入口；保留只读迁移审计数据。

回滚策略：在切换前保留旧 target 字段和 profile version；若新推导器或迁移校验失败，停止新写入、隔离新任务并恢复到旧逻辑的只读/受控完成模式。不得在已产生新 namespace 对象后直接把旧客户端输入重新作为 provider target。

## Open Questions

- 租户和应用的可读 slug 是否在创建后永久不可变，还是只展示不可变 `storage_namespace` 而允许 slug 修改？这不影响核心隔离，但会影响管理界面字段设计。
- 配额的默认值、租户配额分配给应用的审批权限和历史用量保留周期，需要结合运营规则确定。
