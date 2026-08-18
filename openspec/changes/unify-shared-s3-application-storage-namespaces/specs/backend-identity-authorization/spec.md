## MODIFIED Requirements

### Requirement: 用户组与 Scoped RoleBinding
系统 SHALL 支持用户组，并 SHALL 将用户、用户组或应用通过 RoleBinding 绑定到角色、应用逻辑存储空间、canonical prefix 与有效期；文件角色缺少应用或存储资源范围时 MUST NOT 生效。用户组是授权主体但不是认证主体，MUST NOT 拥有密码、登录会话或独立 API 凭据。

#### Scenario: 用户通过组取得应用目录权限
- **WHEN** ACTIVE 用户属于绑定了有效应用目录角色的用户组
- **THEN** 系统 SHALL 仅在该应用命名空间和绑定目录范围内授予该角色操作

#### Scenario: User group attempts to log in
- **WHEN** 调用方使用用户组标识或用户组名称作为登录身份
- **THEN** 系统 SHALL 拒绝认证，且用户组只能通过其成员的已认证身份参与授权

#### Scenario: 用户通过组取得目录权限
- **WHEN** ACTIVE 用户属于绑定了有效目录角色的用户组
- **THEN** 系统 SHALL 仅在绑定资源范围内授予该角色操作

#### Scenario: Application principal uses a group binding
- **WHEN** 应用 API Key 请求文件资源
- **THEN** 系统 SHALL 仅依据该 application principal 的应用范围绑定授权，不得把普通用户的组成员关系伪装成应用登录身份

### Requirement: 授权判定与解释
系统 SHALL 合并有效 allow、应用 deny 优先和 default deny，并 SHALL 同时校验 tenant、application、storage namespace、canonical prefix、主体类型、有效期和 authorization version；授权解释 SHALL 标明直接主体、用户组或应用主体来源。

#### Scenario: Group and direct bindings overlap
- **WHEN** 用户通过组和直接绑定获得 allow，但目标同时命中 deny
- **THEN** 系统 SHALL 返回 DENY 及稳定原因和匹配来源

#### Scenario: Binding crosses application boundary
- **WHEN** RoleBinding 的主体、应用命名空间或 storage space 不属于当前 tenant，或请求目标不属于绑定的 application
- **THEN** 系统 SHALL 拒绝授权并不得泄露目标资源是否存在

#### Scenario: 多个来源同时匹配
- **WHEN** 用户通过组和直接绑定获得 allow，但目标同时命中 deny
- **THEN** 系统 SHALL 返回 DENY 及稳定原因和匹配来源

### Requirement: Authorization enum metadata
统一元数据目录 SHALL 发布授权范围类型和授权效果的稳定枚举：scope 至少包括 tenant、storage_space、directory，effect 至少包括 allow、deny。权限名称和角色详情仍分别由 permission catalog 与 platform roles 接口发布，不得要求前端手写权限字符串。

#### Scenario: Frontend builds an authorization form
- **WHEN** 前端加载元数据目录和权限目录
- **THEN** 前端 SHALL 使用返回的 scope、effect 和 permission value 生成授权表单，并按 description 展示说明

#### Scenario: Unknown authorization enum is submitted
- **WHEN** 请求提交目录中不存在的 scope 或 effect
- **THEN** 系统 SHALL 返回稳定的 validation_failed 错误，不得把未知字符串当作默认授权范围

### Requirement: Identity and authorization enum filters
身份和授权列表接口 SHALL 使用服务端公开的主体类型、用户状态、成员状态、授权来源和授权判定枚举；`GET /users` SHALL 支持 `status` 与 `principal_type`，`GET /members` SHALL 支持 `status`。筛选条件 SHALL 贯穿接口、应用服务、领域校验和持久化查询，并 SHALL 保留租户边界。

#### Scenario: User list is filtered by enum
- **WHEN** 调用方使用目录中的 `status` 或 `principal_type` 查询用户
- **THEN** 系统 SHALL 只返回匹配且属于当前租户的用户，并在 OpenAPI 中声明相同枚举值

#### Scenario: Invalid identity filter is submitted
- **WHEN** 调用方提交目录中不存在的身份或授权枚举值
- **THEN** 系统 SHALL 返回 `422 validation_failed`，不得把未知值当作无筛选条件
