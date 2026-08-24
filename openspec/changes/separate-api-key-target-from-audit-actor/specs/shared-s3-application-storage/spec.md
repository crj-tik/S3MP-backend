## MODIFIED Requirements

### Requirement: Application-owned storage namespace
每个 active 应用 SHALL 拥有一个租户内唯一且稳定的逻辑存储命名空间。命名空间 SHALL 绑定 tenant_id 和 application_id，并 SHALL 在应用生命周期内保持稳定；应用重命名不得隐式改变已存在对象的物理 Key。应用 API Key、其目标应用、storage space 和 namespace SHALL 必须属于同一 tenant_id。应用 API 请求中的 application_code SHALL 在该 tenant_id 内解析为 active 操作应用，仅用于审计，不得改变 API Key 所属目标命名空间或要求操作应用与目标应用相同。

#### Scenario: Application namespace is derived from API Key
- **WHEN** 应用使用 API Key 请求访问相对路径 `reports/2026.xlsx` 并携带同租户操作应用 code
- **THEN** 系统 SHALL 从 API Key 绑定的目标应用推导命名空间，并记录 code 对应应用为操作应用

#### Scenario: Application namespace is derived
- **WHEN** 应用 API Key 请求访问相对路径 `reports/2026.xlsx`
- **THEN** 系统 SHALL 从 API Key 绑定的目标应用、其同租户 storage space 和数据库绑定推导该目标应用命名空间

#### Scenario: Cross-application collaboration uses a target key
- **WHEN** 应用 A 使用同租户应用 B 的有效 API Key，并携带 A 的有效 code
- **THEN** 系统 SHALL 访问 B 的命名空间，而不得将 A 的 code 解释为存储命名空间选择器

#### Scenario: Cross-application identifier is supplied
- **WHEN** 应用 API Key 请求携带另一个同租户 active 应用的 application_code
- **THEN** 系统 SHALL 将该 code 作为操作应用审计主体，并仍访问 API Key 所属目标应用命名空间

#### Scenario: Cross-tenant actor code is supplied
- **WHEN** 应用 API 请求携带只存在于其他租户的 code，或当前租户内不存在的 code
- **THEN** 系统 SHALL 返回拒绝结果且不得访问或探测目标对象

#### Scenario: Cross-tenant representative is supplied
- **WHEN** 应用 API 请求的 actor code 只能解析到其他租户应用，或目标解析使用其他租户的 storage space 或 namespace
- **THEN** 系统 SHALL 返回拒绝结果且不得访问或探测目标对象

#### Scenario: Browser selects an application namespace
- **WHEN** 已认证浏览器用户携带 application_id 请求数据面
- **THEN** 系统 SHALL 从该 application_id 解析同租户目标命名空间并记录当前用户为操作主体
