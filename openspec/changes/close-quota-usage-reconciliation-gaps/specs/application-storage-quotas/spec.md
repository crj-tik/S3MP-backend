## MODIFIED Requirements

### Requirement: Tenant and application quota hierarchy
系统 SHALL 支持租户总配额、应用配额和存储空间配额；应用或存储空间配额不得超过其租户可分配容量。租户、应用和存储空间的响应 SHALL 分别返回 limit、used、reserved、available、测量时间和一致性状态等可计算字段。所有配额范围 SHALL 使用目录中的 `tenant`、`application`、`storage_space` 枚举。

#### Scenario: Application quota exceeds tenant quota
- **WHEN** 管理员为应用设置大于租户剩余可分配容量的配额
- **THEN** 系统 SHALL 拒绝配置并返回稳定的配额校验错误

#### Scenario: Storage space quota is queried
- **WHEN** 管理员查询一个存储空间范围的容量状态
- **THEN** 系统 SHALL 返回该命名空间对应的 limit、used、reserved、available 和统计一致性信息

#### Scenario: Usage is queried
- **WHEN** 管理员查询租户、应用或存储空间的容量状态
- **THEN** 系统 SHALL 返回当前已确认使用量、进行中预留量和可用量，并明确统计时间或一致性状态

## ADDED Requirements

### Requirement: Idempotent deletion release
文件对象成功完成 provider 删除后，系统 SHALL 在同一数据库事务中将文件置为不可用的可追踪终态，并按该文件的实际确认大小从关联的应用/存储空间和租户配额中扣减 `used_bytes`。同一文件的重试、重复回调或重复 Worker 执行 SHALL 不得重复扣减。

#### Scenario: File deletion succeeds
- **WHEN** provider 已确认删除一个可用文件
- **THEN** 系统 SHALL 恰好一次释放该文件占用的所有关联配额，并记录脱敏的配额调整审计事件

#### Scenario: File deletion is retried
- **WHEN** 同一删除任务在数据库提交后再次执行
- **THEN** 系统 SHALL 返回幂等结果，配额使用量不得再次变化

### Requirement: Orphan reservation recovery
系统 SHALL 周期性扫描状态为 `reserved` 的 reservation，并根据关联入库/上传状态和有效期将其结算、释放或隔离。缺少有效关联记录的 reservation SHALL 不得继续占用 `reserved_bytes`，但自动修正 SHALL 保留审计证据。

#### Scenario: Expired reservation is recovered
- **WHEN** reservation 已过期且关联上传未进入成功结算状态
- **THEN** 系统 SHALL 原子释放对应配额的 `reserved_bytes`，并将 reservation 置为 `released`

#### Scenario: Reservation has no valid owner
- **WHEN** reservation 找不到租户、应用或入库记录的有效关联
- **THEN** 系统 SHALL 将其标记为隔离/异常并报告，不得计入可用容量或静默删除证据

### Requirement: Controlled quota reconciliation
系统 SHALL 提供按租户、应用和命名空间执行的受控对账任务。对账 SHALL 比较有效文件投影、共享 S3 对象清单和 reservation 状态，返回差异分类、计算使用量、当前记录值、孤儿对象和无法确认归属的对象；默认模式 SHALL 只读，写入修正 MUST 显式授权且幂等。

#### Scenario: Reconciliation detects size drift
- **WHEN** 数据库文件大小与共享 S3 对象的已验证大小不一致
- **THEN** 对账结果 SHALL 报告大小漂移，不得直接将漂移对象计入正常可用量

#### Scenario: Reconciliation applies a correction
- **WHEN** 具备配额管理权限的受控任务显式执行对账修正
- **THEN** 系统 SHALL 在事务中更新配额使用量、记录修正原因和测量时间，并输出前后值

### Requirement: Quota statistics consistency
配额响应 SHALL 标明统计状态，至少区分实时事务计数、对账一致和存在待处理差异；存在未处理差异或隔离对象时，`available_bytes` SHALL 不得伪装为已完全验证的最终值。

#### Scenario: Statistics have unresolved differences
- **WHEN** 当前范围存在大小漂移、孤儿对象或未处理 reservation
- **THEN** 配额查询 SHALL 返回差异状态和测量时间，且不得声称统计已完全一致
