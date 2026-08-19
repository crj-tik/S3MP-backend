## MODIFIED Requirements

### Requirement: Tenant and application quota hierarchy
系统 SHALL 支持唯一的租户总配额和可选的应用独立配额。租户配额 SHALL 表示该租户在共享 Bucket 中允许使用的总容量；应用独立配额 SHALL 表示从租户总配额中静态划出的容量。没有独立配额的应用 SHALL 使用租户共享剩余池。响应 SHALL 返回 limit、used、reserved、available、allocated 和 consistency 等可计算字段。

#### Scenario: Application quota exceeds tenant allocation
- **WHEN** 管理员为应用设置大于租户总配额扣除其他 active 应用独立配额后的可分配容量
- **THEN** 系统 SHALL 拒绝配置并返回稳定的配额校验错误

#### Scenario: Application quota exceeds tenant quota
- **WHEN** 管理员为应用设置大于租户总配额的配额
- **THEN** 系统 SHALL 拒绝配置并返回稳定的配额校验错误

#### Scenario: Shared pool quota is queried
- **WHEN** 管理员查询租户容量状态
- **THEN** 系统 SHALL 返回租户总容量、独立应用划分总量、共享池容量、共享池已用量、共享池预留量和共享池可用量

#### Scenario: Usage is queried
- **WHEN** 管理员查询租户或应用的容量状态
- **THEN** 系统 SHALL 返回当前已确认使用量、进行中预留量和可用量，并明确统计时间或一致性状态

#### Scenario: Application quota is queried
- **WHEN** 管理员查询具有独立配额的应用容量状态
- **THEN** 系统 SHALL 返回应用独立上限、实际使用量、预留量和可用量，并标识其为独立预留模式

### Requirement: Atomic upload reservation
创建上传或 multipart 会话时，系统 SHALL 在同一事务边界内锁定租户总配额、相关应用配额及 active 应用独立配额汇总，分别检查租户总容量、应用独立容量或共享池容量，并原子增加 reservation；并发请求不得共同通过同一剩余容量检查。

#### Scenario: Concurrent uploads race for shared pool
- **WHEN** 两个未分配应用同时竞争小于单个文件大小的共享池剩余容量
- **THEN** 至多一个请求 SHALL 成功预留，另一个 SHALL 返回配额不足且不得创建可执行的 provider 会话

#### Scenario: Concurrent uploads race for remaining quota
- **WHEN** 两个上传请求同时竞争小于单个文件大小的剩余容量
- **THEN** 至多一个请求 SHALL 成功预留，另一个 SHALL 返回配额不足且不得创建可执行的 provider 会话

#### Scenario: Reserved application is protected from shared consumers
- **WHEN** 未分配应用尝试使用已划给独立配额应用的容量
- **THEN** 系统 SHALL 按共享池上限拒绝超出的请求，即使租户总配额仍有未使用的账面容量

### Requirement: Reservation settlement
成功提交 SHALL 以 HeadObject 或 multipart 完成后的实际大小分别结算租户总量、应用独立量或共享池用量；失败、取消和过期 SHALL 释放对应预留；实际大小超过配额时 SHALL 隔离或受控清理对象而不标记为可用。

#### Scenario: Shared application reservation settles
- **WHEN** 未分配应用的上传成功提交
- **THEN** 系统 SHALL 增加租户总使用量和共享池使用量，不得增加任何应用独立配额使用量

#### Scenario: Declared size differs from actual size
- **WHEN** provider 返回的实际大小大于声明大小并超过应用独立配额、共享池或租户总配额
- **THEN** 系统 SHALL 不得将对象标记为可用，并 SHALL 记录可审计的超额结果

### Requirement: Usage reconciliation
系统 SHALL 提供按租户、应用和命名空间重算或校正使用量的受控任务；重算 SHALL 同时计算租户总使用量、每个独立应用使用量和共享池使用量，并 SHALL 报告孤儿对象、重复记录和无法确认归属的对象。

#### Scenario: Reconciliation calculates shared pool
- **WHEN** 共享 Bucket 中存在租户下多个应用的有效对象
- **THEN** 系统 SHALL 将未配置独立配额的应用对象汇总为共享池使用量，并将独立应用对象单独统计

#### Scenario: Reconciliation finds an orphan object
- **WHEN** 共享 Bucket 中存在无法映射到 active tenant/application namespace 的对象
- **THEN** 系统 SHALL 将其报告为隔离对象，不得计入任何应用可用量或通过文件接口返回

### Requirement: Quota enum filters
配额列表 SHALL 使用目录中的 quota scope、allocation mode、quota status 和 reservation status 枚举，并支持按这些枚举查询。服务层 SHALL 校验 scope 与租户/应用层级的关联，仓储层 SHALL 执行真实筛选并排除已删除租户、应用及孤儿 reservation。

#### Scenario: Quota list is filtered by allocation mode
- **WHEN** 管理员按 `tenant_total` 或 `application_reserved` 查询
- **THEN** 系统 SHALL 只返回对应模式的有效配额，并提供稳定分页结果

#### Scenario: Quota list is filtered by scope and status
- **WHEN** 管理员按目录中的配额范围和预留状态查询
- **THEN** 系统 SHALL 返回同时匹配的租户或应用配额，并提供稳定分页结果

#### Scenario: Quota filter crosses lifecycle boundary
- **WHEN** 查询命中已删除应用或无归属 reservation
- **THEN** 系统 SHALL 排除该记录，不得将其计入 available 或返回为有效配额
