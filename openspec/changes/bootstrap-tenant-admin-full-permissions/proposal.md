## Why

上一版把 `tenant-admin` 错误建模为租户内置角色并自动绑定给初始成员，导致平台管理页无法统一授予该角色，也让平台角色与租户角色职责混淆。平台管理员、平台运营员、平台审计员和租户管理员应处于同一全局用户角色层级，但租户管理员的实际权限必须在用户进入拥有有效 Membership 的租户后才生效。

## What Changes

- 将 `tenant-admin` 纳入平台用户级角色目录，与 `platform_admin`、`platform_operator`、`platform_auditor` 同层级管理。
- 平台管理页面可通过平台角色绑定接口向全局用户授予或撤销 `tenant-admin`。
- 租户创建时不再自动绑定租户内 `tenant-admin` RoleBinding。
- 拥有 `tenant-admin` 平台角色且在目标租户拥有 ACTIVE Membership 的用户，在该租户内获得完整租户权限。
- 没有目标租户 Membership 的平台用户，即使拥有 `tenant-admin`，也不得访问该租户资源。
- 租户权限目录继续过滤 `platform.*`；平台角色权限不得跨租户直接访问数据面。
- 移除旧方案中启动时补全租户 `tenant-admin` 和为存储空间自动创建 `tenant-admin` 文件绑定的逻辑。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend-identity-authorization`: 平台 `tenant-admin` 通过当前租户 Membership 映射为租户内完整权限；租户内不再自动生成同名管理员角色。
- `platform-control-plane`: 平台角色目录和角色绑定支持 `tenant-admin`，租户创建不再隐式授予该角色。
- `backend-api-contract`: 平台角色绑定契约声明 `tenant-admin`，租户权限目录仍不得返回 `platform.*`。

## Impact

- 影响平台角色基线、平台角色授权服务、租户授权依赖、租户创建流程、权限解释和相关测试。
- 可能需要调整平台角色持久化字段或增加平台角色到租户权限的映射逻辑。
- 现有自动生成的租户 `tenant-admin` 绑定需要迁移或失效处理，不能继续作为授权来源。
