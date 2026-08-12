## MODIFIED Requirements

### Requirement: 服务端租户隔离
系统 SHALL 从有效会话或凭证推导 tenant context，所有租户资源查询 SHALL 同时限定 tenant_id 与 resource_id。身份、组、角色、RoleBinding、有效权限和模拟请求 SHALL 在生产运行时通过已装配的应用服务执行，而不是依赖测试注入的服务；不可见的跨租户资源 SHALL 返回 `404 resource_not_found` 且不泄露其存在。

#### Scenario: 替换其他租户资源 ID
- **WHEN** 已认证主体提交其他租户的资源 ID
- **THEN** 系统 SHALL 拒绝且不泄露该资源是否存在

#### Scenario: 生产装配身份授权管理服务
- **WHEN** 数据库已配置的生产应用启动并收到身份或授权管理请求
- **THEN** 系统 SHALL 使用真实的租户范围应用服务处理请求，而不得因服务未装配返回内部错误

### Requirement: 用户组与 Scoped RoleBinding
系统 SHALL 支持用户组，并 SHALL 将用户、用户组或应用通过 RoleBinding 绑定到角色、storage space、canonical prefix 与有效期；文件角色缺少资源范围时 MUST NOT 生效。创建或修改角色 SHALL 原子持久化其权限集合，创建 RoleBinding SHALL 校验授权者的可委派权限和资源范围。

#### Scenario: 用户通过组取得目录权限
- **WHEN** ACTIVE 用户属于绑定了有效目录角色的用户组
- **THEN** 系统 SHALL 仅在绑定资源范围内授予该角色操作

#### Scenario: 更新角色权限
- **WHEN** 管理员更新角色的权限集合
- **THEN** 系统 SHALL 用新集合替换该角色的持久化权限关联，并在后续授权解释中使用更新后的集合

#### Scenario: 尝试超范围委派
- **WHEN** 授权者创建超出自身操作或目录范围的 RoleBinding
- **THEN** 系统 SHALL 拒绝并记录安全事件

### Requirement: 授权判定与解释
系统 SHALL 合并有效 allow、应用 deny 优先和 default deny，并 SHALL 为授权管理员提供有效权限查询与单次模拟。每个受保护的身份和授权管理端点 SHALL 在执行前强制其声明的权限，而不仅将该权限作为契约元数据。

#### Scenario: 多个来源同时匹配
- **WHEN** 用户通过组和直接绑定获得 allow，但目标同时命中 deny
- **THEN** 系统 SHALL 返回 DENY 及稳定原因和匹配来源

#### Scenario: 缺少管理操作权限
- **WHEN** 已认证主体请求其不具有声明管理权限的身份或授权端点
- **THEN** 系统 SHALL 在读取或变更目标资源前返回 `403 permission_denied`

### Requirement: 生命周期即时回收
只有 ACTIVE Membership SHALL 产生用户成员权限；暂停、到期、移除、调组或策略变化 SHALL 推进 authorization version，并使旧会话权限、缓存和未开始任务重新验证。会话 cookie SHALL 在服务端先按与持久化记录相同的单向摘要算法解析，再查询会话；原始会话 token MUST NOT 用作持久化查询值或审计内容。API key SHALL 解析为已启用的 application principal，并 SHALL NOT 被伪装为用户 membership。当同一租户存在多条 membership 记录时，系统 SHALL 遍历全部记录选择第一条 active 的，而非在遇到非 active 记录时停止。`/api/v1/me` SHALL 从已验证的主体和持久化授权状态投影当前租户、可用租户、粗粒度权限与最新 authorization version。

#### Scenario: 用户被暂停
- **WHEN** 管理员把成员状态改为 SUSPENDED
- **THEN** 系统 SHALL 撤销会话、阻止新预签名并使旧授权缓存不可继续使用

#### Scenario: 有效 session cookie 被认证
- **WHEN** 调用方携带有效的 session cookie 请求受保护资源
- **THEN** 系统 SHALL 使用该 cookie 的单向摘要找到会话，并仅在 session、membership、principal 与 authorization version 均有效时创建 PrincipalContext

#### Scenario: 应用 API key 请求文件资源
- **WHEN** 已启用 application 使用有效 API key 请求受保护的文件资源
- **THEN** 系统 SHALL 创建 application principal 上下文，并仅根据该 application 的有效 RoleBinding 授权

#### Scenario: 同一租户多条 membership 时选择 active 的
- **WHEN** 用户在同一租户有两条 membership，第一条为 suspended，第二条为 active
- **THEN** 系统 SHALL 跳过第一条继续检查，选择第二条 active membership 返回 PrincipalContext

#### Scenario: 查询当前主体上下文
- **WHEN** 已认证且 ACTIVE 的主体请求 `/api/v1/me`
- **THEN** 系统 SHALL 返回由服务器持久化状态推导的主体、当前租户、可用租户、粗粒度权限和最新 authorization version

### Requirement: Complete identity and authorization HTTP operations
服务 SHALL 通过已认证、租户范围的 HTTP 端点公开契约声明的用户、成员、组、角色、角色绑定、有效权限与授权模拟操作。每个操作 SHALL 以一致的资源投影、分页、ETag 和错误语义返回，且不得暴露内部 tenant_id、原始持久化字段或未声明字段。

#### Scenario: Effective permissions for another tenant principal
- **WHEN** an authenticated principal requests effective permissions for an identifier outside its tenant
- **THEN** the service SHALL return `404 resource_not_found` without revealing cross-tenant existence

#### Scenario: 管理集合分页
- **WHEN** 调用方列举用户、成员、组、角色或角色绑定
- **THEN** 系统 SHALL 返回包含 `items` 和绑定主体、租户、查询及 authorization version 的 `next_cursor` 的契约页面
