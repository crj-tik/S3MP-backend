## Purpose

为平台管理员提供共享 Bucket 容量下的租户总池和应用独立预留容量管理，使未配置独立配额的应用能够安全共享租户剩余空间，并让所有分配、调整和撤销行为具备可审计的边界。

## ADDED Requirements

### Requirement: Platform quota allocation management
系统 SHALL 允许具备平台配额管理权限的用户创建、查询、调整租户总配额和应用独立配额；租户成员 SHALL 只能读取其所属租户的有效配额状态，不得创建或调整配额。

#### Scenario: Platform assigns a tenant quota
- **WHEN** 平台管理员为 active 租户提交不超过 Bucket 容量的总配额
- **THEN** 系统 SHALL 创建或更新该租户唯一的总配额，并记录操作者、旧值、新值和审计事件

#### Scenario: Platform assigns an application reservation
- **WHEN** 平台管理员为 active 租户下的 active 应用提交应用独立配额
- **THEN** 系统 SHALL 创建该应用唯一的独立配额，并拒绝使所有应用独立配额总和超过租户总配额的请求

#### Scenario: Tenant member attempts allocation
- **WHEN** 没有平台配额管理权限的调用方创建或修改配额
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得改变任何配额记录

### Requirement: Shared pool for unallocated applications
没有应用独立配额的 active 应用 SHALL 共同使用租户总配额扣除所有 active 应用独立配额上限后的共享剩余池；独立配额未使用的容量 SHALL 保留给该应用，不得自动回流共享池。

#### Scenario: Unallocated application consumes shared pool
- **WHEN** 未配置独立配额的应用发起上传预留
- **THEN** 系统 SHALL 按共享池的已用量、预留量和剩余容量进行判断，不得占用已划给独立配额应用的保留容量

#### Scenario: Application reservation is revoked
- **WHEN** 平台管理员撤销一个没有未完成预留且实际使用量为零的应用独立配额
- **THEN** 系统 SHALL 停用该独立配额，并将其容量纳入租户共享池可分配容量

### Requirement: Bucket and allocation ceilings
系统 SHALL 维护平台共享 Bucket 的可分配容量上限；租户总配额不得超过该上限，应用独立配额总和不得超过租户总配额，任何降低配额的操作不得低于相关实际使用量、进行中预留量或已划分应用配额总量。

#### Scenario: Tenant quota exceeds bucket capacity
- **WHEN** 平台管理员提交大于共享 Bucket 配置容量的租户总配额
- **THEN** 系统 SHALL 返回稳定的 `quota_allocation_exceeded` 错误并拒绝写入

#### Scenario: Quota is lowered below active usage
- **WHEN** 调整后的配额小于实际使用量、预留量或应用划分总量
- **THEN** 系统 SHALL 返回稳定的校验错误并保持原配额不变

### Requirement: Quota allocation lifecycle
应用独立配额 SHALL 支持 active、suspended 和 revoked 状态；撤销或停用 SHALL 是可审计的逻辑操作，租户总配额不得被物理删除，租户或应用进入删除状态后关联配额 SHALL 不再参与有效查询和新上传授权。

#### Scenario: Suspended application quota is queried
- **WHEN** 调用方查询有效配额列表
- **THEN** 系统 SHALL 排除 suspended 或 revoked 的应用独立配额，并返回其状态给具备审计权限的历史查询

#### Scenario: Deleted application has quota
- **WHEN** 应用被软删除或所属租户被软删除
- **THEN** 系统 SHALL 阻止该应用继续预留空间，并将其配额从共享池有效分配总量中排除或按迁移策略明确处理

