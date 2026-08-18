## Purpose

为平台账户、租户、应用及其关联数据建立可审计、可恢复且默认安全的软删除生命周期，使状态变化能够沿授权和数据查询边界一致传播。

## ADDED Requirements

### Requirement: Account soft deletion and identity reuse
平台账户 SHALL 支持 `active`、`disabled` 和 `deleted` 生命周期状态，并 SHALL 在软删除时记录 `deleted_at`、删除操作者和删除原因。删除账户 SHALL 撤销其账户会话、平台角色绑定和仍有效的租户会话/成员授权，但 SHALL 保留账户及审计历史。邮箱和系统号 SHALL 通过 PostgreSQL 部分唯一索引仅对非删除账户保持唯一。

#### Scenario: Delete an account
- **WHEN** 具备平台账户管理权限的操作者软删除一个账户
- **THEN** 系统 SHALL 原子写入删除状态和审计元数据，撤销该账户的会话与平台授权，并 SHALL NOT 物理删除账户历史记录

#### Scenario: Reuse a deleted account identity
- **WHEN** 新账户使用已删除账户的邮箱或系统号注册
- **THEN** 系统 SHALL 允许注册；同一邮箱或系统号仍被 active、disabled 或其他非删除账户使用时 SHALL 拒绝重复注册

#### Scenario: Deleted account attempts authentication
- **WHEN** 已删除账户使用密码、账户会话或其旧平台凭证请求服务
- **THEN** 系统 SHALL 拒绝认证并 SHALL NOT 返回账户存在性差异

### Requirement: Tenant and application soft-deletion state machines
租户 SHALL 支持 `active`、`suspended` 和 `deleted`；应用 SHALL 支持现有有效状态、`pending_takeover`、`suspended` 和 `deleted`。`deleted` SHALL 是默认不可见的终态；普通业务操作不得将其恢复。恢复操作 SHALL 仅适用于明确允许恢复的对象，并 SHALL 重新校验父级状态、Owner、唯一标识和授权条件。应用 `pending_takeover` SHALL 保持与删除不同的治理语义。

#### Scenario: Delete a tenant
- **WHEN** 平台管理员软删除一个租户
- **THEN** 系统 SHALL 使租户会话、成员授权、应用、存储空间、文件写入入口和 API Key 新请求失效，并 SHALL 保留租户及其审计和数据清理记录

#### Scenario: Delete an application
- **WHEN** 租户授权管理员软删除一个应用
- **THEN** 系统 SHALL 使应用 API Key、应用 Principal、应用 Owner 关联和应用级操作入口失效，并 SHALL 保留应用元数据和审计记录

#### Scenario: Deleted parent blocks child access
- **WHEN** 租户或应用已处于 `deleted` 状态，调用方请求其子资源、凭证或文件操作
- **THEN** 系统 SHALL 返回统一的未找到或未授权结果，不得通过已知子资源 ID 绕过父级状态

### Requirement: Lifecycle propagation and authorization invalidation
父对象进入 `deleted` 或不可用状态时，系统 SHALL 在同一事务或可验证的受控异步流程中传播子对象失效，包括会话、Membership、Principal、RoleBinding、API Key、存储连接、Storage Space、上传/Multipart 会话和未开始文件操作。所有受影响的 authorization version、撤销时间和审计事件 SHALL 可追踪。

#### Scenario: Tenant deletion revokes active access
- **WHEN** 租户删除事务提交
- **THEN** 该租户的 active Membership、tenant session、有效 RoleBinding、应用 API Key 和待执行数据面操作 SHALL 不能继续获得新的授权

#### Scenario: Delayed worker sees a deleted resource
- **WHEN** 文件 worker 在排队后开始执行操作且其租户、应用或 Storage Space 已被删除
- **THEN** worker SHALL 在访问对象存储前重新验证状态并将操作标记为可审计的 `cancelled` 或 `failed`

### Requirement: State-aware query closure
默认服务层和持久层查询 SHALL 按资源所属层级关联并校验状态，而不得只凭 `tenant_id` 或资源 ID 返回记录。账户、租户、应用、主体、成员、存储资源、API Key、文件和操作的列表、详情、鉴权读模型 SHALL 遵守对应的父级状态过滤；平台审计或清理任务查看已删除对象时 SHALL 使用显式的管理范围参数。

#### Scenario: Tenant user listing excludes invalid identities
- **WHEN** 租户管理员列出用户或成员
- **THEN** 默认结果 SHALL 仅包含 active 租户、active Membership、active 账户和 enabled Principal 的有效记录

#### Scenario: Application listing excludes deleted applications
- **WHEN** 租户调用应用列表或应用详情
- **THEN** 系统 SHALL 排除 deleted 应用；`pending_takeover` 可作为明确的治理状态返回但不得被当作 active 授权主体

#### Scenario: Storage and file listing validates the parent chain
- **WHEN** 调用方列出 Storage Space、文件或查询上传/操作状态
- **THEN** 系统 SHALL 校验 active 租户、active Storage Space、有效应用/Principal（如适用）及对象自身可见状态

### Requirement: Explicit lifecycle administration and audit
系统 SHALL 为账户、租户和应用提供受权限保护的软删除、状态变更和允许范围内的恢复操作；接口响应 SHALL 明确返回生命周期状态和删除元数据的安全子集。每次状态变化 SHALL 记录操作者、目标、前后状态、原因和请求关联标识；默认业务接口 SHALL 不提供隐式包含已删除对象的行为。

#### Scenario: Operator requests historical deleted records
- **WHEN** 具备平台审计或清理权限的操作者使用显式历史查询参数
- **THEN** 系统 SHALL 返回标记为 deleted 的安全摘要，并 SHALL 不恢复其认证、授权或数据面能力

#### Scenario: Unauthorized restore or delete
- **WHEN** 无对应生命周期权限的调用方请求删除、恢复或包含已删除对象的查询
- **THEN** 系统 SHALL 拒绝请求且不得泄露目标资源的敏感字段
