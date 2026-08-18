## Purpose

为租户和应用提供可并发安全的容量配额、使用量、预留量和剩余量管理，确保共享 Bucket 下的文件写入不会因并发或异步流程突破授权容量边界。

## ADDED Requirements

### Requirement: Tenant and application quota hierarchy
系统 SHALL 支持租户总配额和应用配额；应用配额不得超过租户可分配容量，租户和应用的响应 SHALL 分别返回 limit、used、reserved 和 available 等可计算字段。

#### Scenario: Application quota exceeds tenant quota
- **WHEN** 管理员为应用设置大于租户剩余可分配容量的配额
- **THEN** 系统 SHALL 拒绝配置并返回稳定的配额校验错误

#### Scenario: Usage is queried
- **WHEN** 管理员查询租户或应用的容量状态
- **THEN** 系统 SHALL 返回当前已确认使用量、进行中预留量和可用量，并明确统计时间或一致性状态

### Requirement: Atomic upload reservation
创建上传或 multipart 会话时，系统 SHALL 在同一事务边界内检查租户和应用剩余容量并原子增加 reservation；并发请求不得共同通过同一剩余容量检查。

#### Scenario: Concurrent uploads race for remaining quota
- **WHEN** 两个上传请求同时竞争小于单个文件大小的剩余容量
- **THEN** 至多一个请求 SHALL 成功预留，另一个 SHALL 返回配额不足且不得创建可执行的 provider 会话

### Requirement: Reservation settlement
成功提交 SHALL 以 HeadObject 或 multipart 完成后的实际大小结算预留；失败、取消和过期 SHALL 释放预留；实际大小超过配额时 SHALL 隔离或受控清理对象而不标记为可用。

#### Scenario: Declared size differs from actual size
- **WHEN** provider 返回的实际大小大于声明大小并超过可用配额
- **THEN** 系统 SHALL 不得将对象标记为可用，并 SHALL 记录可审计的超额结果

### Requirement: Usage reconciliation
系统 SHALL 提供按租户、应用和命名空间重算或校正使用量的受控任务；重算 SHALL 只统计当前有效命名空间内的可用文件，并 SHALL 报告孤儿对象、重复记录和无法确认归属的对象。

#### Scenario: Reconciliation finds an orphan object
- **WHEN** 共享 Bucket 中存在无法映射到 active tenant/application namespace 的对象
- **THEN** 系统 SHALL 将其报告为隔离对象，不得计入任何应用可用量或通过文件接口返回
