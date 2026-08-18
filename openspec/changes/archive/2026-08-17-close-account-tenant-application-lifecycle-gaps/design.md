## Context

当前模型已经有账户 `active/disabled`、租户 `active/suspended`、应用
`active/pending_takeover`、成员 `removed` 和文件删除状态，但账户、租户和
应用没有统一的 `deleted` 元数据，也没有所有查询都关联父级状态。多个表仍
使用数据库 `ON DELETE CASCADE`，不能把物理删除当作业务删除策略。

## Goals / Non-Goals

**Goals:**

- 建立账户、租户、应用的统一软删除状态和审计字段。
- 使用 PostgreSQL 部分唯一索引实现删除账户的邮箱/系统号复用。
- 让父级状态沿认证、授权、凭证、存储和文件查询链路传播。
- 保留清理与审计所需的历史记录，同时阻断删除对象的新访问。
- 以显式管理查询查看历史对象，避免默认业务接口泄露失效资源。

**Non-Goals:**

- 本 change 不立即物理删除 PostgreSQL 历史数据或 S3 对象；S3 清理由既有文件删除/清理任务承接。
- 不把 `pending_takeover`、`suspended`、`disabled` 误改成 `deleted`。
- 不允许普通业务用户恢复已删除账户、租户或应用。
- 不改变租户内部权限模型的角色语义，只增加生命周期前置条件。

## Decisions

### 1. 使用状态字段加删除元数据，不引入通用 polymorphic 删除表

在账户、租户、应用主表增加 `deleted_at`、`deleted_by`、`deletion_reason`，并将
`deleted` 纳入各自状态枚举/约束。这样查询可以直接使用索引和父表 JOIN，审计
也能保留稳定的目标 ID。通用删除表虽然减少字段重复，但会让每条查询都需要
额外 JOIN，且难以表达各领域已有的状态机。

### 2. 账户身份采用部分唯一索引

删除现有无条件唯一约束，新增 PostgreSQL 部分唯一索引：

```sql
CREATE UNIQUE INDEX uq_user_active_email
  ON user_account (normalized_email)
  WHERE status <> 'deleted';

CREATE UNIQUE INDEX uq_user_active_employee_number
  ON user_account (normalized_employee_number)
  WHERE status <> 'deleted';
```

空系统号不应参与冲突判断；迁移前必须检查并处理现有重复数据。恢复账户前
必须重新检查两个身份字段是否与非删除账户冲突。

### 3. 父级状态作为查询前置条件

仓储层按资源链路集中实现状态条件，服务层负责权限与错误映射：

```text
Account
  └─ Membership ─ Tenant
       └─ Principal ─ Application
                       └─ API Key / Storage / File
```

租户业务读默认要求 `Tenant=active`、`Membership=active`、`User=active`、
`Principal.enabled=true`。应用凭证额外要求 `Application=active`；
`pending_takeover` 仅允许治理读取，不允许新的数据面授权。Storage Space、
FileObject、UploadSession 和 FileOperation 必须继续校验自身状态，并 JOIN
到有效租户/空间/应用链路。

### 4. 删除采用事务内失效 + 异步外部清理

PostgreSQL 事务负责写入父级状态、撤销会话/绑定/Key、推进授权版本和审计事件；
S3 对象删除、旧上传中止和大批量子记录处理通过可重试的清理任务完成。清理
任务必须幂等，并在开始前再次检查父级状态和授权版本，避免删除期间产生新数据。

### 5. 默认隐藏，历史查看显式化

普通列表/详情接口默认不返回 `deleted` 或其子资源。平台审计、清理和合规接口
可以使用显式 `include_deleted` 或专用历史端点，但返回安全摘要，不能因此重新
建立会话、凭证或数据面权限。为避免 IDOR，历史查询仍须经过平台权限和租户范围。

### 6. 恢复是受控操作而非自动反转

账户可以在身份不冲突且平台权限允许时恢复；租户恢复前必须确认其上级平台状态、
成员和存储配置可用；应用恢复前必须确认有效 Owner、有效租户和应用 Principal。
若条件不满足，恢复失败并保留 deleted 状态，不进行部分恢复。

## Risks / Trade-offs

- **[风险]** 现有生产库使用无条件唯一约束且存在重复历史数据。→ **缓解：** 迁移前执行重复扫描，先处理冲突，再创建部分索引；迁移失败时不切换状态写入。
- **[风险]** 查询遗漏父级 JOIN 会造成状态穿透。→ **缓解：** 建立仓储查询矩阵和集成测试，覆盖列表、详情、鉴权读模型、worker 和 API Key。
- **[风险]** 租户删除涉及大量文件和 S3 对象。→ **缓解：** 数据库状态先提交，外部对象走可重试、可观测、幂等清理，不在 HTTP 请求中同步清空大批量对象。
- **[风险]** 账户系统号复用可能影响审计可读性。→ **缓解：** 审计永远保存不可变 user UUID，并同时保存当时的脱敏身份快照，不只保存邮箱或系统号。

## Migration Plan

1. 扫描账户邮箱/系统号重复值及租户、应用已有非法状态。
2. 增加删除元数据列和状态约束，回填为未删除。
3. 删除账户两个无条件唯一约束，创建部分唯一索引。
4. 部署状态感知查询和授权逻辑，再开放软删除接口。
5. 对既有无效会话、Key、成员和孤立资源执行一次幂等收敛任务。
6. 观察删除、恢复、查询过滤和清理任务指标；出现问题时可暂停清理 worker，数据库状态变更通过反向迁移或人工恢复流程处理。
