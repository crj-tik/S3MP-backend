## Purpose

为应用 API Key 建立明确、可撤销且严格限定在应用所属租户内的授权代表关系，使应用能够安全继承一个租户 Membership 的有效用户与用户组权限。

## ADDED Requirements

### Requirement: Application has one tenant-local authorization representative
每个 active 应用 SHALL 可绑定至当前 `tenant_id` 下恰好一个 active Membership；绑定记录 MUST 同时保存 tenant_id、application_id 和 membership_id，并 SHALL 保持应用与 Membership 的同租户约束。应用不得通过全局 user_id 解析其他租户的 Membership。

#### Scenario: Bind application to active membership
- **WHEN** 租户管理员为应用选择一个属于当前租户且状态为 active 的 Membership
- **THEN** 系统 SHALL 创建唯一应用授权代表绑定并返回应用与 Membership 的安全摘要

#### Scenario: Reject cross-tenant membership
- **WHEN** 请求使用其他租户的 membership_id、user_id 或 principal_id 绑定应用
- **THEN** 系统 SHALL 返回 `404 resource_not_found` 或 `422 validation_failed`，不得泄露外租户资源是否存在

#### Scenario: Reject a second representative
- **WHEN** 已有授权代表的应用再次创建同类绑定
- **THEN** 系统 SHALL 要求显式替换或返回稳定冲突错误，不得静默形成多条有效代表关系

### Requirement: Application requests resolve representative membership at authorization time
应用使用 API Key 请求时，系统 SHALL 先认证 application principal，再按 application_id 与 tenant_id 解析当前授权代表 Membership；只有该 Membership、其用户 Principal、所属用户组和相关 RoleBinding 均有效时，才可参与授权判定。应用请求 MUST NOT 被伪装为用户登录会话。

#### Scenario: Representative grants file permission
- **WHEN** active 应用的 API Key scope 包含 `files.write`，且授权代表在目标 storage space 的直接或用户组角色允许 `files.write`
- **THEN** 系统 SHALL 允许符合目录范围的上传操作

#### Scenario: Representative lacks operation permission
- **WHEN** API Key scope 允许 `files.write` 但授权代表的有效租户权限不允许目标操作
- **THEN** 系统 SHALL 返回 `403 permission_denied`

#### Scenario: Representative is suspended
- **WHEN** 应用授权代表 Membership 被暂停、移除、到期或其用户 Principal 被禁用
- **THEN** 系统 SHALL 立即拒绝该应用的新请求和新预签名签发

### Requirement: Effective application authorization is tenant-scoped and auditable
应用最终权限 SHALL 是 API Key scopes、授权代表在当前租户内的有效直接/用户组角色、Storage Space/目录范围、治理策略和操作白名单的交集；显式 deny SHALL 优先。授权解释与审计 SHALL 同时标识 application principal、membership、user principal、tenant 和权限来源。

#### Scenario: Same user belongs to multiple tenants
- **WHEN** 同一用户在 Tenant A 和 Tenant B 具有不同角色，而应用属于 Tenant A
- **THEN** 系统 SHALL 只使用 Tenant A 的 Membership 和角色，不得获得 Tenant B 的权限

#### Scenario: Group-derived permission is evaluated for representative
- **WHEN** 授权代表属于当前租户内绑定了目标 storage space 角色的用户组
- **THEN** 系统 SHALL 将该组权限纳入应用请求的有效权限来源，并在解释中标明 group 来源

#### Scenario: Explicit deny overrides representative allow
- **WHEN** 授权代表从直接角色或用户组获得 allow，但目标同时命中 deny
- **THEN** 系统 SHALL 返回 DENY 并记录匹配的 allow/deny 来源
