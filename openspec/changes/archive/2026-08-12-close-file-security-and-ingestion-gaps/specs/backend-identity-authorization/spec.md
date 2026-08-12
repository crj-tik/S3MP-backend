## MODIFIED Requirements

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
