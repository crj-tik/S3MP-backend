## Context

当前 `quota` 表已经有租户、应用和 storage space 关联字段，也有 used/reserved 字段；文件上传预留会同时检查租户和作用域配额。但新的业务语义要求把租户配额定义为总池，并把应用独立配额视为从总池中静态划出的分区，未配置独立配额的应用使用共享剩余池。现有实现还没有可靠表达分配总量、共享池用量和配额生命周期，也没有平台级的分配入口。

## Goals / Non-Goals

**Goals:**

- 让平台管理员可以管理共享 Bucket 容量、租户总配额和应用独立预留配额。
- 在直传和 multipart 的创建、完成、取消、过期、删除流程中统一执行租户总池、应用分区和共享池校验。
- 让数据库和 S3 对账能够分别计算租户总用量、独立应用用量和共享池用量。
- 以状态和审计记录支持应用配额撤销、租户/应用软删除及历史查询。

**Non-Goals:**

- 不为每个租户创建独立 Bucket。
- 不允许第三方应用自行选择 Bucket、region、endpoint 或配额。
- 不实现未使用独立配额自动回流共享池的弹性超分配模式。
- 不在本 change 中开放普通租户成员创建或调整配额。

## Decisions

### 1. 使用“静态独立预留 + 共享剩余池”模型

定义：

```text
tenant_limit = T
allocated_application_limit = Σ active(application_limit_i)
shared_pool_limit = T - allocated_application_limit
shared_pool_used = tenant_used - Σ active(application_used_i)
shared_pool_reserved = tenant_reserved - Σ active(application_reserved_i)
```

应用存在 active 独立配额时，上传必须同时满足应用上限和租户总上限；应用没有独立配额时，只能消耗共享池。独立配额的未使用部分保持隔离，只有撤销后才回到共享池。这样与“从租户空间中划出一块”的业务含义一致。

替代方案是弹性共享：应用未使用的独立额度可临时被其他应用使用。该方案会引入回收优先级、突发使用和未来归还失败等复杂语义，本 change 不采用。

### 2. 配额记录与生命周期

保留一条租户总配额记录，使用 `tenant_id` 且 `application_id` 为空表示总池；应用独立配额使用 `tenant_id + application_id` 唯一键。新增 `allocation_mode` 和 `status`，避免通过多个 nullable 外键隐式推断业务模式。

storage-space quota 不再作为新业务入口。历史记录不直接物理删除：部署迁移时标记为 legacy/revoked，或在明确无使用量和无预留后转换为应用配额；转换失败的记录进入审计隔离，不能参与共享池计算。

### 3. 平台控制面与租户查询面分离

平台控制面提供：

- `GET /api/v1/platform/quotas?tenant_id=...`
- `POST /api/v1/platform/quotas`
- `PATCH /api/v1/platform/quotas/{quota_id}`
- `DELETE /api/v1/platform/quotas/{quota_id}`，仅用于撤销应用独立配额

租户业务面保留只读查询 `/api/v1/quotas` 及详情接口。平台接口使用 `platform.quotas.read/manage`，租户侧使用 `quotas.read`。租户总配额不物理删除，租户或配额进入 suspended/revoked 状态后由生命周期过滤。

### 4. 在 PostgreSQL 事务内锁定分配集合

每次创建/调整配额和上传预留都必须锁定租户总配额行，并按稳定顺序锁定该租户 active 应用配额行。创建应用配额时，在锁内校验 `Σ application.limit_bytes + new_limit <= tenant.limit_bytes`；共享应用预留时，在锁内计算共享池剩余并增加 tenant reservation。这样避免两个并发分配或上传同时通过旧快照检查。

调整配额时还要锁定相关应用和活跃 reservation，拒绝低于 used/reserved 或低于应用分配总量的更新。配额管理和上传预留使用同一组行锁，避免平台调整与上传竞态。

### 5. 统一 reservation 结算

reservation 记录保存租户配额 ID、应用配额 ID（可空）、分配模式和请求大小。独立应用的 reservation 同时关联租户和应用；共享应用只关联租户并记录 `shared_pool` 模式。完成、取消、过期和删除必须按同一 reservation 反向释放或结算，避免重复扣减。

### 6. Bucket 容量采用显式平台配置

标准 S3/MinIO 的普通对象接口无法可靠提供业务可依赖的 Bucket 最大容量，因此新增 `S3MP_BUCKET_CAPACITY_BYTES` 或等价共享 profile 字段。平台创建/调整租户配额时以该配置作为硬上限；对账任务仍检查实际对象总量，发现超过配置时生成可审计差异，不把容量假设交给客户端。

### 7. 对账按 namespace 分层统计

对象扫描按 `{tenant}/{application}/...` 命名空间归属。先得到租户总物理用量，再按应用分组；有 active 独立配额的应用单独核对，其余应用合并为共享池。未知租户、未知应用、已删除命名空间对象进入隔离差异，不参与有效容量。

## Risks / Trade-offs

- [锁竞争] 同一租户的应用分配和上传会竞争租户总配额行 → 只锁当前租户，保持稳定锁序，并设置短事务；用户规模较小，优先保证正确性。
- [S3 统计成本] 对账需要扫描共享 Bucket 前缀 → 日常写入使用数据库实时预留，S3 扫描作为异步对账，不阻塞上传。
- [历史 storage-space 配额] 旧记录可能无法自动映射 → 迁移前审计，只有安全映射的记录自动转换，其余标记隔离并禁止参与新上传。
- [配额撤销与已有数据] 应用已有使用量时不能简单删除配额 → 仅允许零使用、零预留的独立配额直接撤销；否则要求先扩容、迁移或进入受控回收流程。
- [配置容量不准确] Bucket 实际限制可能与配置不一致 → 启动时校验配置非负且可读，对账报告物理用量与配置上限的差异，并保留平台审计记录。

## Migration Plan

1. 增加 quota allocation mode/status、Bucket 容量配置和必要的索引/约束。
2. 审计现有租户、应用、storage-space 配额；生成迁移报告，不自动删除有使用量或预留量的记录。
3. 创建或确认租户总配额；将可安全映射的 storage-space 配额转换为应用配额，其余标记 legacy/revoked 并隔离。
4. 部署平台配额接口、租户只读接口和新的上传预留算法。
5. 执行只读对账，确认租户总量、应用独立量和共享池量一致后，再允许 apply 模式对账。
6. 若回滚，保留新增状态和审计数据，停止新平台分配入口，恢复旧查询/预留逻辑；不得删除已产生的 reservation 或审计记录。
