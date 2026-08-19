## MODIFIED Requirements

### Requirement: 应用身份与 Owner
系统 SHALL 将应用建模为独立 principal，并 SHALL 要求至少一个有效用户或用户组 Owner；Owner 失效时 SHALL 标记应用待接管而非静默删除。除 Owner 外，应用 SHALL 可绑定一个当前租户内的授权代表 Membership；Owner 关系负责生命周期和接管，授权代表关系负责运行时租户权限，二者不得互相隐式替代。

#### Scenario: 应用创建并绑定授权代表
- **WHEN** 当前租户创建应用并选择一个 active Membership 作为授权代表
- **THEN** 系统 SHALL 保存同租户唯一绑定，并返回不含凭据的代表摘要

#### Scenario: Owner and representative differ
- **WHEN** 应用 Owner 与授权代表是不同的租户成员
- **THEN** 系统 SHALL 分别记录两种关系，并按授权代表计算应用文件权限

#### Scenario: 最后一个 Owner 被停用
- **WHEN** 应用最后一个有效 Owner 失效
- **THEN** 系统 SHALL 原子地标记应用待接管、阻止其 API Key 的新认证并通知租户管理员

#### Scenario: 存在已停用 Owner 记录
- **WHEN** 应用仍有 Owner 记录但所有 Owner 的 membership 或主体均已失效
- **THEN** 系统 SHALL 将该应用视为失主，而不得把 Owner 记录本身视为有效 Owner

### Requirement: 权限交集与限流
最终权限 SHALL 是 Key scope、应用授权代表在当前租户内的有效直接和用户组权限、目录策略、租户治理及操作白名单的交集，并 SHALL 按 Key、应用和租户限流。

#### Scenario: scope 允许但代表目录不允许
- **WHEN** Key scope 包含上传但授权代表无目标目录写权限
- **THEN** 系统 SHALL 拒绝上传

#### Scenario: scope 允许但目录不允许
- **WHEN** Key scope 包含上传但应用无目标目录写权限
- **THEN** 系统 SHALL 拒绝上传

#### Scenario: Representative is revoked
- **WHEN** 应用授权代表绑定被撤销
- **THEN** 系统 SHALL 拒绝应用新的受保护请求，但不泄露其他租户成员的权限信息
