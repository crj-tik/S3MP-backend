## Purpose

实现服务端强制执行的多租户身份与访问控制，覆盖用户、成员、用户组、角色、资源范围、有效权限解释、即时回收和访问审查，为所有文件及管理操作提供统一授权基础。
## Requirements
### Requirement: 服务端租户隔离
系统 SHALL 从有效会话或凭证推导 tenant context，所有租户资源查询 SHALL 同时限定 tenant_id 与 resource_id。

#### Scenario: 替换其他租户资源 ID
- **WHEN** 已认证主体提交其他租户的资源 ID
- **THEN** 系统 SHALL 拒绝且不泄露该资源是否存在

### Requirement: 用户组与 Scoped RoleBinding
系统 SHALL 支持用户组，并 SHALL 将用户、用户组或应用通过 RoleBinding 绑定到角色、应用逻辑存储空间、canonical prefix 与有效期；文件角色缺少应用或存储资源范围时 MUST NOT 生效。用户组是授权主体但不是认证主体，MUST NOT 拥有密码、登录会话或独立 API 凭据。应用 SHALL 可通过唯一的当前租户 Membership 授权代表使用该 Membership 的用户和用户组角色，但应用请求仍必须以 application principal 认证。

#### Scenario: 用户通过组取得应用目录权限
- **WHEN** ACTIVE 用户属于绑定了有效应用目录角色的用户组
- **THEN** 系统 SHALL 仅在该应用命名空间和绑定目录范围内授予该角色操作

#### Scenario: User group attempts to log in
- **WHEN** 调用方使用用户组标识或用户组名称作为登录身份
- **THEN** 系统 SHALL 拒绝认证，且用户组只能通过其成员的已认证身份参与授权

#### Scenario: 用户通过组取得目录权限
- **WHEN** ACTIVE 用户属于绑定了有效目录角色的用户组
- **THEN** 系统 SHALL 仅在绑定资源范围内授予该角色操作

#### Scenario: Application representative uses a group binding
- **WHEN** 应用 API Key 请求文件资源且其当前租户授权代表属于绑定了目标 storage space 的用户组
- **THEN** 系统 SHALL 将该用户组角色纳入应用权限判定，并 SHALL 记录应用主体和代表 Membership 的来源

#### Scenario: Cross-tenant group is ignored
- **WHEN** 授权代表用户在其他租户属于具有更高权限的用户组
- **THEN** 系统 SHALL 不使用该组权限

#### Scenario: Application principal uses a group binding
- **WHEN** 应用 API Key 请求文件资源
- **THEN** 系统 SHALL 仅依据当前应用授权代表及其租户范围绑定授权，不得把普通用户的组成员关系伪装成应用登录身份

### Requirement: Role-binding scope filters preserve authorization boundaries
The role-binding list SHALL support filtering by `storage_space_id` while
retaining current-tenant isolation and existing role-binding visibility rules.
The filter SHALL match the binding's persisted logical storage-space scope and
MUST NOT treat a canonical path prefix alone as a match for another space.

#### Scenario: Authorized operator lists bindings for a space
- **WHEN** an authorized tenant operator requests role bindings with a valid storage-space identifier in the current tenant
- **THEN** the response SHALL contain only bindings scoped to that storage space

#### Scenario: Caller supplies another tenant's storage space
- **WHEN** a caller supplies a storage-space identifier that is not active and owned by the current tenant
- **THEN** the API SHALL return no cross-tenant binding records and SHALL not disclose the foreign resource

### Requirement: 授权判定与解释
系统 SHALL 合并有效 allow、应用 deny 优先和 default deny，并 SHALL 同时校验 tenant、application、storage namespace、canonical prefix、主体类型、有效期和 authorization version；对于 application principal，授权解释 SHALL 标明其当前授权代表 Membership、用户 Principal、用户组和直接绑定来源。

#### Scenario: Group and direct bindings overlap
- **WHEN** 用户通过组和直接绑定获得 allow，但目标同时命中 deny
- **THEN** 系统 SHALL 返回 DENY 及稳定原因和匹配来源

#### Scenario: Binding crosses application boundary
- **WHEN** RoleBinding 的主体、应用命名空间或 storage space 不属于当前 tenant，或请求目标不属于绑定的 application
- **THEN** 系统 SHALL 拒绝授权并不得泄露目标资源是否存在

#### Scenario: 多个来源同时匹配
- **WHEN** 用户通过组和直接绑定获得 allow，但目标同时命中 deny
- **THEN** 系统 SHALL 返回 DENY 及稳定原因和匹配来源

#### Scenario: Application representative changes
- **WHEN** 应用授权代表被替换或撤销
- **THEN** 系统 SHALL 推进应用授权版本，使旧缓存、排队任务和旧授权解释在重新验证时失效

### Requirement: 生命周期即时回收
只有 ACTIVE Membership SHALL 产生用户成员权限；暂停、到期、移除、调组或策略变化 SHALL 推进 authorization version，并使旧会话权限、缓存和未开始任务重新验证。会话 cookie SHALL 在服务端先按与持久化记录相同的单向摘要算法解析，再查询会话；原始会话 token MUST NOT 用作持久化查询值或审计内容。API key SHALL 解析为已启用的 application principal，并 SHALL 在每次受保护文件请求时重新验证其当前租户授权代表 Membership；不得按全局 user_id 读取其他租户权限。

#### Scenario: 用户被暂停
- **WHEN** 管理员把成员状态改为 SUSPENDED
- **THEN** 系统 SHALL 撤销会话、阻止新预签名并使旧授权缓存和未开始任务不可继续使用

#### Scenario: 有效 session cookie 被认证
- **WHEN** 调用方携带有效的 session cookie 请求受保护资源
- **THEN** 系统 SHALL 使用该 cookie 的单向摘要找到会话，并仅在 session、membership、principal 与 authorization version 均有效时创建 PrincipalContext

#### Scenario: 应用 API key 请求文件资源
- **WHEN** 已启用 application 使用有效 API key 请求受保护的文件资源
- **THEN** 系统 SHALL 创建 application principal 上下文，并仅根据该 application 的有效 RoleBinding 授权

#### Scenario: 同一租户多条 membership 时选择 active 的
- **WHEN** 用户在同一租户有两条 membership，第一条为 suspended，第二条为 active
- **THEN** 系统 SHALL 跳过第一条继续检查，选择第二条 active membership 返回 PrincipalContext

#### Scenario: 应用授权代表被暂停
- **WHEN** 应用 API Key 请求文件资源前，其授权代表 Membership 被暂停
- **THEN** 系统 SHALL 拒绝请求并使应用相关缓存和未开始任务不可继续使用

#### Scenario: 应用 Key remains an application identity
- **WHEN** 应用使用 API Key 请求受保护资源
- **THEN** 系统 SHALL 保留 application principal 作为认证和审计主体，仅把代表 Membership 作为当前租户授权来源

### Requirement: 委派与访问审查
普通授权者 SHALL 只能够授予自身明确可委派操作和资源范围的子集；系统 SHALL 验证直接或通过角色间接形成的授权均不扩大调用者的当前权限、规范目录范围或有效期限。不可委派权限、对调用者自身的直接授权、对已绑定角色的越权权限扩展以及对系统角色的修改 MUST NOT 生效。拥有当前租户平台 `tenant-admin` 的用户可在该租户内委派完整租户权限，但仍 MUST 遵守目标租户、资源范围、有效期和禁止自我授权约束。系统 SHALL 支持对直接授权、敏感目录、用户组和应用进行定期 Access Review。

#### Scenario: 尝试超范围委派
- **WHEN** 授权者授予超出自身操作或目录范围的 RoleBinding
- **THEN** 系统 SHALL 拒绝并记录安全事件

#### Scenario: 修改已绑定角色以扩大权限
- **WHEN** 调用方尝试向一个已有有效 RoleBinding 的角色增加自身无权委派或不可委派的权限
- **THEN** 系统 SHALL 返回 `403 delegation_exceeds_authority` 且不得改变角色或任何绑定主体的有效权限

#### Scenario: 修改系统角色或进行自我授权
- **WHEN** 调用方尝试修改系统角色，或创建使自身获得新权限的 RoleBinding
- **THEN** 系统 SHALL 拒绝请求并记录安全事件

#### Scenario: Tenant admin delegates a non-delegable tenant permission
- **WHEN** a user has platform `tenant-admin` and an ACTIVE Membership in the current tenant and grants a role containing a permission normally marked non-delegable
- **THEN** the system SHALL allow the delegation within the current tenant when the target is not the caller and the grant scope and expiry are valid

### Requirement: Complete identity and authorization HTTP operations
The service SHALL expose the contract-declared member detail, group membership, effective-permission, and authorization-simulation operations through authenticated tenant-scoped HTTP endpoints.

#### Scenario: Effective permissions for another tenant principal
- **WHEN** an authenticated principal requests effective permissions for an identifier outside its tenant
- **THEN** the service SHALL return `404 resource_not_found` without revealing cross-tenant existence

### Requirement: Account and tenant sessions remain distinct
The system SHALL validate global account sessions independently from tenant
sessions. A valid account session alone MUST NOT be treated as a tenant
PrincipalContext or confer tenant permissions.

#### Scenario: Logged-in account has no selected tenant
- **WHEN** an account session calls a tenant-scoped endpoint before selecting a tenant
- **THEN** the system SHALL reject the request as requiring tenant authentication

### Requirement: Global accounts support company employee identity
The global user identity SHALL support a unique non-secret company employee number in addition to email, while keeping account identity separate from tenant membership, roles, and permissions.

#### Scenario: Account context exposes safe identity
- **WHEN** an authenticated account requests its account context
- **THEN** the response SHALL include email, employee number, display name and user identifier without password hash or session material

### Requirement: Authorization enum metadata
统一元数据目录 SHALL 发布授权范围类型和授权效果的稳定枚举：scope 至少包括 tenant、storage_space、directory，effect 至少包括 allow、deny。权限名称和角色详情仍分别由 permission catalog 与 platform roles 接口发布，不得要求前端手写权限字符串。

#### Scenario: Frontend builds an authorization form
- **WHEN** 前端加载元数据目录和权限目录
- **THEN** 前端 SHALL 使用返回的 scope、effect 和 permission value 生成授权表单，并按 description 展示说明

#### Scenario: Unknown authorization enum is submitted
- **WHEN** 请求提交目录中不存在的 scope 或 effect
- **THEN** 系统 SHALL 返回稳定的 validation_failed 错误，不得把未知字符串当作默认授权范围

### Requirement: Identity and authorization enum filters
身份和授权列表接口 SHALL 使用服务端公开的主体类型、用户状态、成员状态、授权来源和授权判定枚举；`GET /users` SHALL 支持 `status` 与 `principal_type`，`GET /members` SHALL 支持 `status`。筛选条件 SHALL 贯穿接口、应用服务、领域校验和持久化查询，并 SHALL 保留租户边界。

#### Scenario: User list is filtered by enum
- **WHEN** 调用方使用目录中的 `status` 或 `principal_type` 查询用户
- **THEN** 系统 SHALL 只返回匹配且属于当前租户的用户，并在 OpenAPI 中声明相同枚举值

#### Scenario: Invalid identity filter is submitted
- **WHEN** 调用方提交目录中不存在的身份或授权枚举值
- **THEN** 系统 SHALL 返回 `422 validation_failed`，不得把未知值当作无筛选条件

### Requirement: Platform tenant-admin derives current-tenant authority
The authorization service SHALL treat platform `tenant-admin` as a global-user
role. For a tenant request, it SHALL derive the complete tenant permission set
only when the authenticated user has an ACTIVE Membership in the current
tenant. It SHALL never merge Membership, RoleBinding, or permissions from
another tenant.

#### Scenario: Active membership receives full tenant authority
- **WHEN** a user has platform `tenant-admin` and an ACTIVE Membership in the current tenant
- **THEN** every published non-platform tenant permission SHALL be effective for that request

#### Scenario: Missing or inactive membership is denied
- **WHEN** a user has platform `tenant-admin` but no ACTIVE Membership in the current tenant
- **THEN** the tenant request SHALL be denied and no tenant permissions SHALL be derived

#### Scenario: Cross-tenant membership is not reused
- **WHEN** a user has an ACTIVE Membership in tenant A and requests tenant B without an ACTIVE Membership there
- **THEN** tenant A's authorization SHALL not affect the decision for tenant B

#### Scenario: Revocation invalidates derived authority
- **WHEN** the platform `tenant-admin` grant expires or is revoked
- **THEN** the authorization version/cache SHALL be invalidated and subsequent checks SHALL deny derived tenant permissions

### Requirement: Tenant-local tenant-admin is not an implicit authorization source
The authorization service SHALL not treat a tenant-local role named
`tenant-admin` created by legacy bootstrap logic as the source of platform
tenant-admin authority. Ordinary tenant roles SHALL continue to require explicit
tenant RoleBinding or group membership.

#### Scenario: Legacy tenant-admin binding is not trusted
- **WHEN** a legacy tenant-local `tenant-admin` Role or RoleBinding remains in storage
- **THEN** authorization SHALL ignore it as a platform tenant-admin grant

#### Scenario: Ordinary tenant role still requires binding
- **WHEN** a user has no platform `tenant-admin` grant and no explicit binding to a tenant role
- **THEN** the user SHALL not receive that role's permissions
