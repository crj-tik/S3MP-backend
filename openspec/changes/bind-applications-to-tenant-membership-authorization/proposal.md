## Why

当前应用 API Key 使用独立 application principal 授权，但应用创建流程没有清晰的应用级角色授权入口；给租户成员或用户组授予文件角色不会传递到应用，导致已创建应用和 Key 在真实上传时被 `default_deny` 拒绝。需要建立应用与当前租户内唯一 Membership 的显式授权代表关系，使应用能够继承该成员在同一租户内的直接和用户组权限，同时保持应用身份、Key scope 与租户隔离。

## What Changes

- **BREAKING** 为每个应用增加唯一的租户内授权代表 Membership 绑定；应用创建或绑定变更时只能选择当前 `tenant_id` 下的有效 Membership。
- **BREAKING** 应用 API Key 的文件授权从“仅 application principal 的 RoleBinding”改为“绑定 Membership 的有效租户权限”，并继续与 API Key scope、Storage Space/目录范围、治理策略和操作白名单求交集。
- 应用请求仍使用 application principal 认证；后端仅在服务端解析其授权代表，不把应用伪装成用户会话或跨租户查询用户权限。
- 绑定成员的直接角色和用户组角色可参与应用权限计算；显式 deny、成员失效、租户/应用失效和授权版本变化必须立即回收应用访问。
- 应用 Owner 关系继续负责应用生命周期和接管，不再被隐式当作文件授权代表；Owner 与授权代表可分别审计。
- 增加应用授权代表的查询、创建、替换和撤销契约，并为权限解释和审计返回应用、Membership、用户主体及权限来源。
- 前端应用详情页提供“授权代表/有效权限”管理与验证入口，不再要求用户通过成员角色间接猜测应用是否可上传。

## Capabilities

### New Capabilities

- `application-membership-authorization`: 应用与单一当前租户 Membership 的授权代表关系、生命周期、跨租户校验和权限解释。

### Modified Capabilities

- `openspec/specs/backend-identity-authorization/spec.md`: 修改应用主体的授权来源，使应用可在严格租户边界内解析绑定 Membership 的用户及用户组权限，并保留 deny 优先、有效期和授权版本规则。
- `openspec/specs/backend-application-access/spec.md`: 增加应用授权代表关系，区分 Owner 与运行时授权来源，并定义绑定变更对 API Key 请求的影响。
- `openspec/specs/backend-file-storage/spec.md`: 修改文件数据面应用请求的授权条件，使其使用绑定 Membership 的有效文件权限，同时继续要求 Storage Space/目录范围。
- `openspec/specs/shared-s3-application-storage/spec.md`: 补充应用命名空间与授权代表 Membership 必须属于同一租户的约束。

## Impact

- 影响身份、应用、授权和文件服务的领域模型、SQLAlchemy 模型、迁移、仓储和授权解析链路。
- 新增应用授权代表 HTTP API、OpenAPI 契约、权限解释字段和审计事件；现有应用需要数据迁移或显式补绑授权代表。
- API Key 认证仍返回 application principal，但文件操作需要重新解析当前 Membership 状态和授权版本；缓存、延迟任务和预签名流程必须同步更新。
- 前端需要在应用创建/详情流程中选择当前租户成员，并展示继承自该成员及用户组的有效权限。
- 现有仅依赖 application principal RoleBinding 的应用授权行为发生变化，属于兼容性和安全策略变更；必须提供迁移、拒绝原因和回滚策略。
