## Purpose

为应用 API Key 提供可持久化、可审计的应用内目录范围，使一个凭据只能访问其目标应用根目录或明确指定的子目录。

## ADDED Requirements

### Requirement: API Key directory scope lifecycle
系统 SHALL 允许在为目标应用签发 API Key 时指定可选的应用内目录范围。未指定目录时，Key 的目录范围 SHALL 为该目标应用命名空间的根目录；指定目录时，系统 SHALL 规范化并持久化该目录，且不得接受物理 key、租户前缀、应用前缀、路径穿越或编码歧义。Key 的详情与列表响应 SHALL 返回不含 secret 的目录范围摘要。

#### Scenario: Key is issued for the application root
- **WHEN** 管理员签发 API Key 且未提供存取目录
- **THEN** 系统 SHALL 将该 Key 限定为目标应用的根目录，并不得把未提供目录解释为其他应用或租户的根目录

#### Scenario: Key is issued for a child directory
- **WHEN** 管理员为目标应用签发 Key 并提供 `contracts/2026`
- **THEN** 系统 SHALL 将规范化的 `contracts/2026` 保存为该 Key 的目录范围，并将该目录登记为目标应用命名空间内可用的逻辑目录

#### Scenario: Invalid directory is submitted
- **WHEN** 签发请求包含绝对路径、`..`、反斜杠、空段、控制字符或物理对象 key
- **THEN** 系统 SHALL 返回 `422 validation_failed`，且不得签发 Key 或创建对象

### Requirement: API Key directory scope enforcement
应用 API 的每项文件数据面操作 SHALL 将调用方提供的文件 key 或列举前缀解释为相对于经认证 API Key 的目录范围。系统 SHALL 在任何元数据查询、对象存储访问、预签名签发或异步工作开始前，派生并验证目标应用内的完整 relative key；该 Key 仅可访问其目录范围自身及以该范围加 `/` 开始的后代路径。

#### Scenario: Key accesses a file below its directory scope
- **WHEN** 范围为 `contracts/2026` 的 Key 上传相对 key `case-a.md`
- **THEN** 系统 SHALL 只在目标应用的 `contracts/2026/case-a.md` 位置执行该操作

#### Scenario: Key attempts sibling-directory access
- **WHEN** 范围为 `contracts/2026` 的 Key 请求访问目标应用内的 `contracts/2025/case-a.md`
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得探测或访问该对象

#### Scenario: Similar directory prefix is requested
- **WHEN** 范围为 `team` 的 Key 请求 `team2/report.csv`
- **THEN** 系统 SHALL 返回 `403 permission_denied`，不得按普通字符串前缀将 `team2` 视为 `team` 的后代

### Requirement: Directory scope persists through long-lived operations
直传上传、multipart、预签名、文件操作和异步任务 SHALL 保存创建时 API Key 的目录范围证据，并在续传、完成、中止、执行和重试时复核该范围、目标应用状态和 Key 状态。系统 MUST NOT 允许使用 upload ID、multipart ID、operation ID 或已存在记录转换到 Key 范围之外的路径。

#### Scenario: Multipart completion is resumed
- **WHEN** 目录受限 Key 创建的 multipart 会话被完成
- **THEN** 系统 SHALL 使用会话保存的目录范围和派生路径复核完成请求，而不得接受客户端替换的应用内 key

#### Scenario: Key is revoked before deferred execution
- **WHEN** 目录受限 Key 已被吊销且其排队文件操作尚未执行
- **THEN** 系统 SHALL 取消或失败该操作，且不得访问对象存储
