## Why

资源详情页需要围绕应用、逻辑存储空间和平台审计资源加载关联数据。当前响应已经包含这些关联字段，但三个列表接口只能返回宽列表，导致前端必须拉取全量后再过滤，随着租户数据增长会带来额外延迟、分页不准确和不必要的数据暴露范围。

## What Changes

- 为 `GET /api/v1/storage_spaces` 增加 `application_id` 查询过滤，贯穿 API、服务层和持久层。
- 为 `GET /api/v1/role_bindings` 增加 `storage_space_id` 查询过滤，基于绑定 scope 过滤逻辑存储空间。
- 为 `GET /api/v1/platform/audit-events` 增加 `resource_type` 与 `resource_id` 查询过滤。
- 让三类列表的不透明分页游标绑定完整查询条件，防止过滤条件变化后复用错误游标。
- 同步 OpenAPI 契约、接口说明、服务端口和持久化查询测试。
- 保持响应结构、权限要求、共享 Bucket 模型和现有未传过滤参数时的兼容行为不变。

## Capabilities

### New Capabilities

无。本 Change 为既有列表查询能力增加服务端过滤维度。

### Modified Capabilities

- `openspec/specs/backend-api-contract/spec.md`: 三个列表接口公开并约束新的查询参数和游标语义。
- `openspec/specs/tenant-storage-isolation/spec.md`: 存储空间过滤必须仍限制在当前租户的有效命名空间内。
- `openspec/specs/backend-identity-authorization/spec.md`: 角色绑定按逻辑存储空间过滤时不得越过当前租户和现有权限边界。
- `openspec/specs/platform-control-plane-management/spec.md`: 平台审计列表支持按资源类型和资源标识筛选，且继续受平台审计读取权限保护。

## Impact

- API：`src/s3mp/storage/api/router.py`、`src/s3mp/authorization/api/router.py`、`src/s3mp/platform/api/control_router.py`。
- 应用服务和端口：对应 storage、authorization、platform service/store Protocol。
- 持久化：StorageSpace、RoleBinding、PlatformAuditEvent 的 SQL 查询及索引评估。
- 契约：`contracts/openapi.yaml` 和运行时 OpenAPI 文档。
- 测试：HTTP 参数校验、服务层透传、数据库过滤、分页游标条件隔离。
