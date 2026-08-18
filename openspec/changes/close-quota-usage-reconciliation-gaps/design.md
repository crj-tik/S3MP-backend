## Context

当前上传入库已经在 PostgreSQL 行锁下维护租户和应用/空间 reservation，并在 HeadObject 验证后结算实际大小。文件删除则采用异步 provider 操作，但完成删除时直接移除 `file_object`，没有与配额账本建立一次性扣减边界。现有 `scripts/reconcile_storage_quotas.py` 只汇总数据库有效文件，且默认不处理 reservation、不扫描共享 S3。

本设计遵循共享 Bucket、服务端派生命名空间和“数据库是控制面、S3 是数据面”的约束。详细行为以本 change 的 delta specs 为准。

## Goals / Non-Goals

**Goals:**

- 让上传、删除、过期、失败和重试都能安全更新配额。
- 让 `used_bytes`、`reserved_bytes` 和 `available_bytes` 具备明确的一致性状态。
- 通过共享 Bucket 命名空间扫描发现数据库与 provider 的漂移。
- 让自动对账默认只读、显式修正、可审计、可重试。
- 使 tenant/application/storage_space 三类范围在领域、查询和契约中保持一致。

**Non-Goals:**

- 不改变共享 Bucket 的平台所有权模型。
- 不允许客户端自行选择 Bucket、物理 key 或扫描前缀。
- 不在本 change 中实现对象内容恢复、跨 Bucket 迁移或账单计费。
- 不把孤儿对象自动删除；清理必须由单独的人工审批或保留策略处理。

## Decisions

### 1. 文件终态保留与一次性账本调整

将 `file_object` 的成功删除从物理删除调整为带保留期的不可用终态，例如 `deleted`。删除 Worker 只有在 provider 删除成功后，调用一个数据库事务边界完成：锁定文件、锁定关联配额、确认文件仍处于 `deleting`、扣减所有关联配额并写入删除/配额调整事件，最后转换为 `deleted`。状态条件保证重复 Worker、重复回调和进程重启不会重复扣减。

选择保留终态而不是立即删除，是因为配额扣减需要幂等依据，对账需要知道历史文件是否已经释放，审计需要保留实际大小和范围；定期保留清理只删除已过保留期且已完成账本调整的终态。

### 2. 配额范围与父子更新

统一使用 `tenant`、`application`、`storage_space`。一个文件可能同时影响租户配额和应用/空间配额；所有更新按照稳定 UUID 顺序锁定，避免并发上传、删除、对账之间产生死锁。应用空间优先使用 application quota，未绑定应用的空间使用 storage-space quota；租户配额始终作为上层容量边界。

### 3. Reservation 回收状态机

Worker 增加 reservation 扫描：

```text
reserved
  ├─ 入库已提交且已验证 ──> settled
  ├─ 入库失败/取消/过期 ──> released
  ├─ 关联记录缺失/租户已删除 ──> quarantined + 告警
  └─ 仍在有效期内 ──> 保持 reserved
```

扫描必须按租户和 reservation 行锁执行，并以状态条件保证重试幂等。`quarantined` 是否作为公开 reservation 枚举需要与现有目录统一；若不公开，则通过对账差异状态和审计事件暴露，而不是伪装成 released。

### 4. 双来源对账

对账分成数据库投影和 provider 清单两侧：

1. 从 `file_object`、`storage_space`、`application`、`tenant` 读取 active 命名空间内的可用文件。
2. 通过对象存储端口按平台 Bucket 和命名空间前缀分页列举对象，并读取必要的大小/ETag 元数据。
3. 以派生的物理 key 作为匹配键，分类为 matched、db_missing、provider_missing、size_mismatch、duplicate_mapping、orphan_object。
4. 只将 matched 且状态有效的对象纳入建议使用量；差异写入报告并将 quota consistency 标记为 `drift_detected`。

默认 dry-run 只产生报告。显式 apply 仅修正数据库计数和测量状态，不自动删除或移动未知 S3 对象。每次 apply 使用 reconciliation run id，重复执行同一 run id 不重复写调整。

### 5. Worker 调度与管理入口

文件 Worker 继续负责上传/删除恢复，同时按配置周期执行轻量 reservation 回收；完整 provider inventory 对账使用独立批次，避免阻塞实时文件操作。先保留 CLI 的 dry-run/apply 兼容入口，再提供受权限保护的管理触发/查询接口或内部任务入口；两者共用同一 application service，不允许脚本复制业务规则。

### 6. 统计响应

配额响应增加统计状态、测量时间、最近对账运行标识和差异摘要等非敏感字段。`available_bytes` 继续按 `limit - used - reserved` 计算，但当存在未处理差异时必须标识为非完全一致；前端可据此展示“实时计数/已对账/存在差异”，不自行推断。

### 7. 数值与迁移

对配额、文件大小、reservation 请求/实际大小使用足以覆盖生产 Bucket 的整数类型，优先迁移 PostgreSQL `INTEGER` 到 `BIGINT`。迁移先回填并校验非负值，再建立约束；部署顺序为兼容读取、迁移、启用新写入和终态清理。已有 `deleting` 文件需由一次性修复任务按 provider 结果收敛，不能直接批量扣减。

## Risks / Trade-offs

- [Provider 列举成本高] → 使用命名空间前缀、分页、批次上限和可恢复游标；实时上传不等待完整对账。
- [S3 与数据库暂时不一致] → 引入明确 consistency 状态，差异对象不计入可用量且进入审计/告警。
- [删除成功但数据库提交失败] → Worker 重试必须以 `deleting` 状态重放；provider 删除采用幂等语义，事务只允许一次账本调整。
- [配额锁与对账锁竞争] → 所有路径按配额 UUID 排序锁定，并限制对账批次大小。
- [旧数据没有完整 application_id/namespace] → 对账分类为无法确认归属，不自动计入或删除，提供人工报告。
- [终态保留增加数据库容量] → 使用 retention job 清理已完成且超过保留期的终态，同时保留摘要审计。

## Migration Plan

1. 增加/迁移文件终态、配额数值类型、对账运行和差异报告所需结构。
2. 发布兼容版本：能够读取旧状态，新增字段可为空，暂停自动物理删除。
3. 对既有 `deleting`、`reserved` 和配额记录执行只读审计，先处理异常再启用 apply。
4. 启用删除账本事务和 reservation 回收 Worker。
5. 启用共享 S3 inventory 对账 dry-run，核对报告后再开放受控 apply。
6. 更新 OpenAPI/元数据/前端生成契约，最后启用终态保留清理。

回滚时保留已写入的终态、对账报告和审计事件；可以暂停新 Worker 修正，不回滚已提交的配额调整，以免重复计数。若必须回退应用版本，旧版本必须至少忽略新终态而不能将其重新视为可用文件。

## Open Questions

- provider 是否能稳定提供带 continuation token 的对象列举和批量 Head 元数据；若不能，需要在适配器层实现受限分页。
- 生产保留期和孤儿对象人工审批流程的具体时长由运维策略确定，不改变本 change 的账本和对账边界。
