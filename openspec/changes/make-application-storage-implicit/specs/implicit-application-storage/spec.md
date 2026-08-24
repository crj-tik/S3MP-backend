## Purpose

定义租户和应用天然拥有的存储层级，使存储路径完全由服务端创建并只读展示，业务用户无需创建、绑定、解绑或选择独立存储空间。

## ADDED Requirements

### Requirement: Tenant has an implicit default storage root
每个租户 SHALL 天然拥有以其不可变 slug 为路径段的默认存储根上下文。调用方 MUST NOT 创建、选择、替换或提交该根路径对应的 Bucket、连接和 provider prefix。

#### Scenario: Tenant is created
- **WHEN** 平台成功创建 slug 为 `sft-test` 的租户
- **THEN** 系统 SHALL 同时建立路径为 `sft-test` 的默认存储根上下文，且不要求后续初始化操作

### Requirement: Application storage is created atomically
每个应用 SHALL 在创建事务内自动获得唯一内部存储记录和不可变命名空间 `<tenant_slug>/<application_id>`。应用、主体、Owner、授权代表和内部存储任一创建失败 SHALL 回滚整个事务。

#### Scenario: Application is created under a tenant
- **WHEN** 在租户 `sft-test` 下创建应用并分配 ID `oca_id`
- **THEN** 应用 SHALL 立即可使用 `sft-test/oca_id`，且调用方无需创建或绑定存储空间

#### Scenario: Internal storage creation fails
- **WHEN** 应用的内部存储记录无法建立
- **THEN** 系统 SHALL 回滚应用创建并返回稳定错误，不得留下无存储应用

### Requirement: Application storage is display-only
应用列表、详情和创建响应 SHALL 返回只读存储摘要，至少包含命名空间、可用状态以及查询用量和配额所需信息。请求模型 MUST NOT 接受存储空间、Bucket、连接、根路径或 namespace 覆盖字段。

#### Scenario: Application detail is rendered
- **WHEN** 前端显示应用详情
- **THEN** 前端 SHALL 直接展示服务端返回的路径、状态、用量和配额，不提供创建、绑定、解绑或选择存储空间控件

### Requirement: Existing applications are reconciled safely
系统 SHALL 为每个可唯一证明租户和应用归属的既有应用回填唯一内部存储记录，并保持已经分配的合法物理 Key 不变。冲突或无法证明归属的记录 SHALL 被报告和隔离。

#### Scenario: Existing namespace conflicts
- **WHEN** 迁移发现重复 namespace、跨租户绑定或一个应用存在多个活动内部空间
- **THEN** 系统 SHALL 阻止该应用文件变更并输出可审计冲突，不得静默选择其中一个记录

