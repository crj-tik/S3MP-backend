## Context

当前三个列表接口已经返回可用于关联展示的字段，但查询链路在路由层、应用服务端口和 SQL 持久层都没有对应过滤参数。三类列表均采用基于 ID 的不透明游标；游标签名/缓存键必须包含完整过滤条件。现有租户、应用、逻辑存储空间和平台权限边界必须保持不变。

## Goals / Non-Goals

**Goals:**

- 将 `application_id`、`storage_space_id`、`resource_type`、`resource_id` 从 HTTP 查询参数贯穿到服务层和持久层。
- 在 SQL 层先过滤、再执行 `limit + 1` 分页，保证后续页不漏记录。
- 将所有过滤条件规范化后纳入分页游标查询指纹。
- 更新 OpenAPI 参数描述、运行时 Swagger 和针对跨租户/分页的测试。

**Non-Goals:**

- 不改变共享 Bucket、S3 namespace、配额或文件授权模型。
- 不新增资源表、迁移脚本或新的权限项。
- 不新增通用全文搜索或多字段 OR 查询。
- 不移除前端暂时可用的客户端过滤能力。

## Decisions

### 1. 使用三个明确的资源过滤参数

- `list_storage_spaces(application_id: UUID | None)`：按应用过滤逻辑存储空间。
- `list_role_bindings(storage_space_id: UUID | None)`：按绑定 scope 的逻辑存储空间过滤。
- `list_platform_audit_events(resource_type: str | None, resource_id: str | None)`：资源类型和资源标识分别过滤，多个条件使用 AND。

选择明确参数而不是立即引入 `scope_type + scope_id`，因为当前接口的资源语义和前端页面都是确定的，避免过早抽象造成兼容和校验复杂度。

### 2. 过滤在持久层完成

路由层只负责 UUID/长度/枚举等输入校验；应用服务层负责透传并保持授权检查；Repository 在租户和生命周期条件基础上追加过滤条件，然后统一执行排序、`limit + 1` 和 next cursor 计算。这样不会把无关租户或无关资源先读入应用层，也避免客户端分页失真。

存储空间查询必须继续 join/约束 active tenant、active application、active connection 和 active storage space。角色绑定查询必须在当前 tenant_id 范围内匹配绑定表的 `storage_space_id`。平台审计查询继续由平台权限依赖保护，资源过滤只缩小结果集。

### 3. 游标指纹包含规范化过滤集合

为每个列表构造稳定查询指纹：

```text
storage_spaces:application_id=<uuid-or-empty>:status=<status>
role_bindings:principal_id=<uuid-or-empty>:storage_space_id=<uuid-or-empty>
platform_audit_events:action=<value-or-empty>:resource_type=<value-or-empty>:resource_id=<value-or-empty>
```

所有分页请求使用同一组参数生成指纹；游标指纹不匹配时沿用现有的无效游标错误，不允许静默切换结果集。

### 4. 索引按实际查询计划评估

先复用现有主键、租户、状态和 scope 索引完成实现；通过 PostgreSQL `EXPLAIN` 或集成测试观察规模增长后的计划。只有在查询计划显示需要时，再增加复合索引，例如 storage space 的 `(tenant_id, application_id, status, id)`、role binding 的 `(tenant_id, storage_space_id, id)` 和 audit event 的 `(resource_type, resource_id, id)`，避免当前阶段无证据地增加迁移。

## Risks / Trade-offs

- [Risk] 旧客户端携带不带新过滤参数的游标继续请求 → 过滤条件为空时保持原查询指纹；带过滤参数的游标使用新的完整指纹并拒绝跨条件复用。
- [Risk] 外部租户 ID 被用作过滤参数探测资源 → 过滤始终在当前 tenant_id 和 active 资源约束内执行，只返回空集合或既有资源错误，不返回跨租户记录。
- [Risk] `resource_id` 是字符串而不是统一 UUID → 保持审计模型既有字符串语义，增加长度约束并按精确匹配，不擅自转换为 UUID。
- [Risk] 前端仍保留客户端过滤造成重复逻辑 → 契约发布后前端可以逐页切换到服务端参数，客户端过滤作为兼容兜底，二者结果应通过联调测试对齐。

## Migration Plan

1. 先实现路由、服务端口、Repository 过滤和游标指纹，并补单元/集成测试。
2. 更新 `contracts/openapi.yaml` 与运行时 Swagger，确认三组参数和分页描述一致。
3. 部署 API；不需要数据库迁移，旧请求保持兼容。
4. 通过前端页面逐项切换服务端过滤；若出现异常，可回退前端参数使用，后端新参数不影响旧调用。

## Follow-up Hardening

- Role-binding queries filtered by `storage_space_id` must join the storage space,
  application, connection, and tenant lifecycle records so inactive or legacy
  namespaces are not returned.
- Audit filter values are trimmed once at the HTTP boundary and the normalized
  values are reused for both SQL predicates and cursor fingerprints.
- The new Repository argument is appended after the existing positional paging
  arguments to preserve older integrations that call the port positionally.
