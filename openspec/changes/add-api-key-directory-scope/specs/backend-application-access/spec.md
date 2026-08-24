## MODIFIED Requirements

### Requirement: 权限交集与限流
应用 API Key 请求的最终权限 SHALL 是 Key scope、Key 绑定的目标应用有效状态、Key 自身目录范围、目标应用目录策略、租户治理及操作白名单的交集，并 SHALL 按 Key、目标应用和租户限流。请求 `application_code` 仅用于解析同租户有效的操作应用并写入审计，MUST NOT 选择目标应用、扩大 Key 目录范围或被要求拥有目标目录权限。

#### Scenario: scope 允许但 Key 目录范围不允许
- **WHEN** Key scope 包含上传但请求相对路径在该 Key 指定目录范围之外
- **THEN** 系统 SHALL 拒绝上传，且不得调用对象存储

#### Scenario: scope 允许但目录不允许
- **WHEN** Key scope 包含上传但目标应用目录策略不允许由 Key 目录范围与请求路径派生的完整相对路径
- **THEN** 系统 SHALL 拒绝上传

#### Scenario: scope 允许但代表目录不允许
- **WHEN** Key scope 包含上传但请求 code 对应操作应用不拥有目标目录权限
- **THEN** 系统 SHALL 仍以目标 Key scope、Key 目录范围、目标应用状态和目录策略判定请求，不得将操作应用目录权限作为额外拒绝条件

#### Scenario: scope and Key directory scope allow the request
- **WHEN** Key scope 包含上传，目标应用和租户可用，且请求相对路径位于该 Key 的目录范围内
- **THEN** 系统 SHALL 按目标应用目录策略继续授权并在通过后允许上传

#### Scenario: scope 允许但目标应用目录策略不允许
- **WHEN** Key scope 和 Key 目录范围允许上传但目标应用目录策略拒绝该完整相对路径
- **THEN** 系统 SHALL 拒绝上传

#### Scenario: Audit actor application is invalid
- **WHEN** 请求 code 未解析为 API Key 所属租户内的 active 应用
- **THEN** 系统 SHALL 拒绝请求且不得访问目标目录

#### Scenario: Representative is revoked
- **WHEN** 目标应用的旧授权代表绑定被撤销
- **THEN** 系统 SHALL 按当前目标应用、API Key 生命周期、Key 目录范围和目录策略处理请求，不得把已撤销代表错误当作操作主体
