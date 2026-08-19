## MODIFIED Requirements

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

#### Scenario: Application principal uses a group binding
- **WHEN** 应用 API Key 请求文件资源
- **THEN** 系统 SHALL 仅依据该 application principal 的应用范围绑定授权，不得把普通用户的组成员关系伪装成应用登录身份

#### Scenario: Cross-tenant group is ignored
- **WHEN** 授权代表用户在其他租户属于具有更高权限的用户组
- **THEN** 系统 SHALL 不使用该组权限

### Requirement: 授权判定与解释
系统 SHALL 合并有效 allow、应用 deny 优先和 default deny，并 SHALL 同时校验 tenant、application、storage namespace、canonical prefix、主体类型、有效期和 authorization version；对于 application principal，授权解释 SHALL 标明其当前授权代表 Membership、用户 Principal、用户组和直接绑定来源。

#### Scenario: Binding crosses application boundary
- **WHEN** RoleBinding 的主体、应用命名空间、授权代表 Membership 或 storage space 不属于当前 tenant，或请求目标不属于绑定的 application
- **THEN** 系统 SHALL 拒绝授权并不得泄露目标资源是否存在

#### Scenario: Group and direct bindings overlap
- **WHEN** 用户通过组和直接绑定获得 allow，但目标同时命中 deny
- **THEN** 系统 SHALL 返回 DENY 及稳定原因和匹配来源

#### Scenario: 多个来源同时匹配
- **WHEN** 用户通过组和直接绑定获得 allow，但目标同时命中 deny
- **THEN** 系统 SHALL 返回 DENY 及稳定原因和匹配来源

#### Scenario: Application representative changes
- **WHEN** 应用授权代表被替换或撤销
- **THEN** 系统 SHALL 推进应用授权版本，使旧缓存、排队任务和旧授权解释在重新验证时失效

### Requirement: 生命周期即时回收
只有 ACTIVE Membership SHALL 产生用户成员权限；暂停、到期、移除、调组或策略变化 SHALL 推进 authorization version，并使旧会话权限、缓存和未开始任务重新验证。API key SHALL 解析为已启用的 application principal，并 SHALL 在每次受保护文件请求时重新验证其当前租户授权代表 Membership；不得按全局 user_id 读取其他租户权限。

#### Scenario: 应用授权代表被暂停
- **WHEN** 应用 API Key 请求文件资源前，其授权代表 Membership 被暂停
- **THEN** 系统 SHALL 拒绝请求并使应用相关缓存和未开始任务不可继续使用

#### Scenario: 用户被暂停
- **WHEN** 管理员把成员状态改为 SUSPENDED
- **THEN** 系统 SHALL 撤销会话、阻止新预签名并使旧授权缓存和未开始任务不可继续使用

#### Scenario: 有效 session cookie 被认证
- **WHEN** 调用方携带有效的 session cookie 请求受保护资源
- **THEN** 系统 SHALL 使用该 cookie 的单向摘要找到会话，并仅在 session、membership、principal 与 authorization version 均有效时创建 PrincipalContext

#### Scenario: 应用 API key 请求文件资源
- **WHEN** 已启用 application 使用有效 API key 请求受保护的文件资源
- **THEN** 系统 SHALL 创建 application principal 上下文，并根据该 application 的有效授权代表及其当前租户权限授权

#### Scenario: 同一租户多条 membership 时选择 active 的
- **WHEN** 用户在同一租户有两条 membership，第一条为 suspended，第二条为 active
- **THEN** 系统 SHALL 跳过第一条继续检查，选择第二条 active membership 返回 PrincipalContext

#### Scenario: 应用 Key remains an application identity
- **WHEN** 应用使用 API Key 请求受保护资源
- **THEN** 系统 SHALL 保留 application principal 作为认证和审计主体，仅把代表 Membership 作为当前租户授权来源
