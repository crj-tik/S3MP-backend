## MODIFIED Requirements

### Requirement: 权限交集与限流
应用 API Key 请求的最终权限 SHALL 是 Key scope、目标应用的有效状态、操作应用 code 的同租户有效性、目录策略、租户治理及操作白名单的交集，并 SHALL 按 Key、目标应用和租户限流。操作应用 code 仅用于审计主体归属，MUST NOT 被要求拥有目标应用目录权限或授权代表权限。

#### Scenario: Target key scope permits a cross-application operation
- **WHEN** 应用 A 持有应用 B 的 active API Key，Key scope 允许上传，且 A 的 code 在 B 所属租户中为 active
- **THEN** 系统 SHALL 允许在 B 的目标目录中上传并将 A 记录为操作应用

#### Scenario: Key scope denies the operation
- **WHEN** API Key 不包含请求操作所需的 scope
- **THEN** 系统 SHALL 拒绝操作，即使请求 code 对应同租户 active 应用

#### Scenario: Audit actor application is invalid
- **WHEN** 请求 code 未解析为 API Key 所属租户内的 active 应用
- **THEN** 系统 SHALL 拒绝请求且不得访问目标目录

#### Scenario: Target application is revoked
- **WHEN** API Key 所属目标应用被暂停、删除或不再可用
- **THEN** 系统 SHALL 拒绝新的受保护请求，不因操作应用 code 有效而放行

#### Scenario: scope 允许但目录不允许
- **WHEN** Key scope 包含上传但目标应用的目录策略不允许该请求相对路径
- **THEN** 系统 SHALL 拒绝上传

#### Scenario: scope 允许但代表目录不允许
- **WHEN** Key scope 包含上传但请求 code 对应操作应用不拥有目标目录权限
- **THEN** 系统 SHALL 仍以目标 Key scope、目标应用状态和目录策略判定请求，不得将操作应用的目录权限作为额外拒绝条件

#### Scenario: Representative is revoked
- **WHEN** 目标应用的旧授权代表绑定被撤销
- **THEN** 系统 SHALL 按当前目标应用和 API Key 生命周期规则处理请求，不得把已撤销代表错误当作跨应用 API Key 请求的操作主体
