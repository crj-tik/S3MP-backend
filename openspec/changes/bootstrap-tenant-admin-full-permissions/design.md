## Context

平台角色授予全局用户，租户角色绑定到租户成员。当前实现把 `tenant-admin` 作为租户内置角色自动创建，导致权限来源与平台管理界面脱节。详见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 将 `tenant-admin` 纳入平台角色，与 `platform_admin`、`platform_operator`、`platform_auditor` 同层管理。
- 通过当前请求的租户上下文和该用户的 ACTIVE Membership，把平台授予的 `tenant-admin` 转换为当前租户的完整租户权限。
- 保留普通租户角色、用户组、应用授权代表和文件范围校验。
- 移除租户创建及启动时对租户本地 `tenant-admin` 的隐式创建、绑定和存储空间补绑。

**Non-Goals:**

- 不允许平台角色直接访问租户数据面；必须有明确的租户上下文。
- 不改变普通平台角色的既有语义。
- 不让应用 Principal 直接继承平台角色；应用仍通过绑定成员获得该成员在当前租户的授权。

## Decisions

1. **平台角色作为唯一 tenant-admin 来源。** 在平台角色基线和授权接口中登记 `tenant-admin`。不再选择继续保留租户本地同名角色，避免同名角色产生两套语义和绕过平台授权审计。
2. **授权桥接按当前租户求值。** 构建租户 `PrincipalContext` 时先解析全局用户的有效平台角色，再检查当前 `tenant_id` 下的 ACTIVE Membership；仅当两者同时满足时注入完整租户权限来源。不会查询或合并用户在其他租户的 Membership、RoleBinding 或权限。
3. **平台角色与租户会话分层。** `platform_admin/operator/auditor` 仍不能凭平台会话调用租户数据面；`tenant-admin` 也必须通过租户会话或明确租户上下文才能生效。
4. **取消隐式初始化。** 租户创建只保证租户和初始 ACTIVE Membership 的原子创建，不自动写入租户本地 tenant-admin Role/RoleBinding，也不在启动时重建这类绑定。既有遗留数据通过一次性迁移清理或标记停用。
5. **权限目录按作用域过滤。** 租户权限目录继续排除 `platform.*`；平台角色目录单独展示四个同层平台角色，避免前端把平台权限混入租户角色表单。
6. **版本与缓存失效。** 平台角色授予、撤销、过期和 Membership 状态变更必须递增授权版本/清理缓存，使 tenant-admin 的派生权限及时生效或失效。

## Risks / Trade-offs

- [平台 tenant-admin 可作用于用户加入的多个租户] → 每个租户仍要求 ACTIVE Membership，平台授予/撤销记录完整审计并支持过期时间。
- [旧租户本地 tenant-admin 数据残留] → 部署迁移删除或停用旧角色绑定，并在授权桥接中禁止把遗留同名角色当作平台授权来源。
- [撤销后的短暂缓存窗口] → 使用 authorization version 和请求级当前租户校验，必要时在撤销事务中主动失效缓存。
- [应用调用权限链更复杂] → 应用仍解析到绑定成员，再按该成员在当前租户的有效授权求值，增加针对跨租户和非活跃成员的回归测试。

## Migration Plan

1. 发布平台角色基线、授权桥接和契约变更。
2. 执行数据迁移：识别旧租户本地 `tenant-admin` Role/RoleBinding，停用或删除其绑定，并保留审计记录。
3. 部署后验证：平台界面授予用户 `tenant-admin`，用户具有某租户 ACTIVE Membership 时可执行全部租户权限；无 Membership 或撤销后立即拒绝。
4. 回滚时停止新的桥接逻辑并恢复旧授权代码；迁移数据从审计备份恢复，避免把平台授权误恢复为租户本地授权。
