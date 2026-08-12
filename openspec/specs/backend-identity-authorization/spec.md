## Purpose

实现服务端强制执行的多租户身份与访问控制，覆盖用户、成员、用户组、角色、资源范围、有效权限解释、即时回收和访问审查，为所有文件及管理操作提供统一授权基础。

## Requirements

### Requirement: 服务端租户隔离
系统 SHALL 从有效会话或凭证推导 tenant context，所有租户资源查询 SHALL 同时限定 tenant_id 与 resource_id。

#### Scenario: 替换其他租户资源 ID
- **WHEN** 已认证主体提交其他租户的资源 ID
- **THEN** 系统 SHALL 拒绝且不泄露该资源是否存在

### Requirement: 用户组与 Scoped RoleBinding
系统 SHALL 支持用户组，并 SHALL 将用户、用户组或应用通过 RoleBinding 绑定到角色、storage space、canonical prefix 与有效期；文件角色缺少资源范围时 MUST NOT 生效。

#### Scenario: 用户通过组取得目录权限
- **WHEN** ACTIVE 用户属于绑定了有效目录角色的用户组
- **THEN** 系统 SHALL 仅在绑定资源范围内授予该角色操作

### Requirement: 授权判定与解释
系统 SHALL 合并有效 allow、应用 deny 优先和 default deny，并 SHALL 为授权管理员提供有效权限查询与单次模拟。

#### Scenario: 多个来源同时匹配
- **WHEN** 用户通过组和直接绑定获得 allow，但目标同时命中 deny
- **THEN** 系统 SHALL 返回 DENY 及稳定原因和匹配来源

### Requirement: 生命周期即时回收
只有 ACTIVE Membership SHALL 产生用户成员权限；暂停、到期、移除、调组或策略变化 SHALL 推进 authorization version，并使旧会话权限、缓存和未开始任务重新验证。会话 cookie SHALL 在服务端先按与持久化记录相同的单向摘要算法解析，再查询会话；原始会话 token MUST NOT 用作持久化查询值或审计内容。API key SHALL 解析为已启用的 application principal，并 SHALL NOT 被伪装为用户 membership。当同一租户存在多条 membership 记录时，系统 SHALL 遍历全部记录选择第一条 active 的，而非在遇到非 active 记录时停止。

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

### Requirement: 委派与访问审查
授权者 SHALL 只能授予自身明确可委派操作和资源范围的子集；系统 SHALL 支持对直接授权、敏感目录、用户组和应用进行定期 Access Review。

#### Scenario: 尝试超范围委派
- **WHEN** 授权者授予超出自身操作或目录范围的 RoleBinding
- **THEN** 系统 SHALL 拒绝并记录安全事件
### Requirement: Complete identity and authorization HTTP operations
The service SHALL expose the contract-declared member detail, group membership, effective-permission, and authorization-simulation operations through authenticated tenant-scoped HTTP endpoints.

#### Scenario: Effective permissions for another tenant principal
- **WHEN** an authenticated principal requests effective permissions for an identifier outside its tenant
- **THEN** the service SHALL return `404 resource_not_found` without revealing cross-tenant existence
