## MODIFIED Requirements

### Requirement: 生命周期即时回收
只有 ACTIVE Membership SHALL 产生用户成员权限；暂停、到期、移除、调组或策略变化 SHALL 推进 authorization version，并使旧会话权限、缓存和未开始任务重新验证。会话 cookie SHALL 在服务端先按与持久化记录相同的单向摘要算法解析，再查询会话；原始会话 token MUST NOT 用作持久化查询值或审计内容。API Key SHALL 解析为已启用的 application principal，并 SHALL NOT 被伪装为用户 membership。当同一租户存在多条 membership 记录时，系统 SHALL 遍历全部记录选择第一条 active 的，而非在遇到非 active 记录时停止。application principal 的 RoleBinding 或状态变化同样 SHALL 使未开始任务重新验证。

#### Scenario: 用户被暂停
- **WHEN** 管理员把成员状态改为 SUSPENDED
- **THEN** 系统 SHALL 撤销会话、阻止新预签名并使旧授权缓存和未开始任务不可继续使用

#### Scenario: 有效 session cookie 被认证
- **WHEN** 调用方携带有效 session cookie 请求受保护资源
- **THEN** 系统 SHALL 使用该 cookie 的单向摘要找到会话，并仅在 session、membership、principal 与 authorization version 均有效时创建 PrincipalContext

#### Scenario: 应用 API key 请求文件资源
- **WHEN** 已启用 application 使用有效 API key 请求受保护的文件资源
- **THEN** 系统 SHALL 创建 application principal 上下文，并仅根据该 application 的有效 RoleBinding 与 Key scope 授权

#### Scenario: 同一租户多条 membership 时选择 active 的
- **WHEN** 用户在同一租户有两条 membership，第一条为 suspended，第二条为 active
- **THEN** 系统 SHALL 跳过第一条继续检查，选择第二条 active membership 返回 PrincipalContext

### Requirement: Complete identity and authorization HTTP operations
服务 SHALL 通过已认证、租户范围的 HTTP 端点公开契约声明的用户、成员、组、角色、角色绑定、有效权限与授权模拟操作。每个操作 SHALL 以一致的资源投影、分页、ETag 和错误语义返回，且不得暴露内部 tenant_id、原始持久化字段或未声明字段。分页 cursor SHALL 绑定调用者、租户、查询过滤条件、排序和 authorization version；跨页遍历不得漏掉或重复稳定排序中的记录。

#### Scenario: 管理集合分页
- **WHEN** 调用方列举用户、成员、组、角色或角色绑定
- **THEN** 系统 SHALL 返回包含 `items` 和绑定主体、租户、查询及 authorization version 的 `next_cursor` 的契约页面

#### Scenario: 边界记录进入下一页
- **WHEN** 查询结果超过请求的 page limit 一个或多个记录
- **THEN** 下一页 SHALL 从当前页最后一个已返回记录之后开始，并返回前一页额外探测到的记录

#### Scenario: Cursor 被用于不同过滤器
- **WHEN** 调用方将某个管理列表 cursor 用于另一主体、过滤条件、排序或 authorization version
- **THEN** 服务 SHALL 返回 `400 validation_failed` 且不得返回不匹配查询的结果

#### Scenario: Effective permissions for another tenant principal
- **WHEN** 已认证主体请求其租户外标识符的有效权限
- **THEN** 系统 SHALL 返回 `404 resource_not_found` 且不得泄露跨租户资源是否存在
