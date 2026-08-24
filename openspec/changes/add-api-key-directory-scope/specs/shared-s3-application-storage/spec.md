## MODIFIED Requirements

### Requirement: Server-derived shared-bucket object key
系统 SHALL 将物理对象 Key 推导为稳定的租户/应用命名空间加规范化应用内相对路径。对于应用 API Key，服务端 SHALL 将经认证 Key 的可选目录范围与调用方提供的 Key-relative path 组合成完整应用内相对路径；未设置目录范围时 SHALL 使用应用根目录。调用方 MUST NOT 提交完整物理 Key、Bucket、租户前缀、应用前缀或 Key 范围之外的应用内路径来选择 provider 目标。

#### Scenario: Same relative key in two applications
- **WHEN** 两个租户或两个应用都提交 `data/a.json`
- **THEN** 系统 SHALL 将其解析为互不相同的物理 Key

#### Scenario: Same Key-relative key in different Key scopes
- **WHEN** 同一目标应用中两个 Key 分别限定为 `inbound` 与 `outbound`，且都提交 `data/a.json`
- **THEN** 系统 SHALL 将它们解析为同一应用命名空间中互不相同的物理 Key

#### Scenario: Default root scope is derived
- **WHEN** 未指定目录范围的 API Key 提交 `data/a.json`
- **THEN** 系统 SHALL 将其解析为目标应用命名空间内的 `data/a.json`

#### Scenario: Prefix traversal is attempted
- **WHEN** Key-relative path 或签发时的目录范围包含 `/` 开头、空段、`.`、`..`、反斜杠、百分号编码歧义或控制字符
- **THEN** 系统 SHALL 在任何 S3 调用前返回 `422 validation_failed`
