## MODIFIED Requirements

### Requirement: 生命周期即时回收
只有 ACTIVE Membership SHALL 产生权限；暂停、到期、移除、调组或策略变化 SHALL 推进 authorization version，并使旧会话权限、缓存和未开始任务重新验证。当同一租户存在多条 membership 记录时，系统 SHALL 遍历全部记录选择第一条 active 的，而非在遇到非 active 记录时停止。

#### Scenario: 用户被暂停
- **WHEN** 管理员把成员状态改为 SUSPENDED
- **THEN** 系统 SHALL 撤销会话、阻止新预签名并使旧授权缓存不可继续使用

#### Scenario: 同一租户多条 membership 时选择 active 的
- **WHEN** 用户在同一租户有两条 membership，第一条为 suspended，第二条为 active
- **THEN** 系统 SHALL 跳过第一条继续检查，选择第二条 active membership 返回 PrincipalContext