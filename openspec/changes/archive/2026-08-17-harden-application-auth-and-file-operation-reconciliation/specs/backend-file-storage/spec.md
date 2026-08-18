## MODIFIED Requirements

### Requirement: Canonical Key 与目录授权
系统 SHALL 对对象 key 执行唯一规范校验并拒绝路径穿越、反斜杠、控制字符和编码歧义；每个文件、上传、下载签名、multipart、删除和对象变更请求 SHALL 在调用对象存储前，以认证主体、storage space、canonical relative key、操作和当前 authorization version 进行授权。物理 Bucket key SHALL 仅由服务端将获授权的 relative key 与 storage space root prefix 派生，授权与 S3 执行 SHALL 使用相同 Bucket、key 和方法。异步或延迟执行的操作 SHALL 在开始执行前重新确认主体状态、授权版本、Key scope（如适用）及当前资源权限。

#### Scenario: 授权对象与执行对象不同
- **WHEN** 拟执行的 Bucket、key 或方法与已授权命令不一致
- **THEN** 系统 SHALL 在调用 S3 前拒绝

#### Scenario: 未授权主体访问同租户文件
- **WHEN** 已认证主体对其没有有效 RoleBinding 的文件、前缀、上传会话或 multipart 会话执行操作
- **THEN** 系统 SHALL 返回 `403 permission_denied`，且不得仅因 tenant_id 匹配而允许

#### Scenario: 排队操作在撤权后开始
- **WHEN** 文件操作排队后、执行前，其 acting principal 被停用、Key 被吊销、授权版本变化或当前路径权限被撤销
- **THEN** 系统 SHALL 不执行对象变更，并记录可审计的 `cancelled` 或 `failed` 结果

### Requirement: 对象变更状态机
复制 SHALL 校验源读和目标写；移动还 SHALL 校验源删除，并在复制验证后删除源。部分失败 MUST NOT 报告完整成功。异步对象变更 SHALL 持久化 pending、running、retry_wait、succeeded、failed、partial_failure 和 cancelled 结果，并对可恢复故障提供幂等重试。

#### Scenario: 移动删源失败
- **WHEN** 目标复制验证成功但源删除失败
- **THEN** 系统 SHALL 保存可恢复的 `partial_failure` 状态

#### Scenario: Worker 在执行中断
- **WHEN** 已领取对象操作的执行者在记录最终结果前中断或 lease 到期
- **THEN** 系统 SHALL 允许另一执行者安全重试，且不得将操作错误标记为成功

### Requirement: Coordinated object lifecycle services
文件查询、上传、multipart、对象操作、配额和审计用例 SHALL 通过使用租户范围持久化和对象存储端口的应用服务执行。它们 SHALL 在外部存储工作前持久化操作意图，并在验证后记录完成、失败或部分失败结果。持久化操作意图 SHALL 被受控 worker 自动领取和收敛，而非永久停留在 pending。

#### Scenario: Source deletion fails after a verified move copy
- **WHEN** 移动操作验证目标对象成功但无法删除源
- **THEN** 对象操作服务 SHALL 持久化并返回可恢复的 `partial_failure` 结果，而非报告完全成功

#### Scenario: 已接受的 copy 操作
- **WHEN** 有权调用方提交有效 copy 操作并收到 `202`
- **THEN** 系统 SHALL 最终将该操作记录收敛为 `succeeded`、`failed`、`partial_failure` 或 `cancelled` 中的一种终态，并提供可查询结果
