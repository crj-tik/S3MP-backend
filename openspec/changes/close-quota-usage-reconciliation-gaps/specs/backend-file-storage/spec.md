## ADDED Requirements

### Requirement: File deletion and quota ledger boundary
文件删除 SHALL 先持久化可恢复的删除意图；仅在 provider 删除成功并完成数据库终态转换后，系统才可释放文件对应的配额使用量。删除失败、授权失效或 provider 不可用时，文件占用 SHALL 保留并进入可重试或人工处理状态。

#### Scenario: Provider deletion fails
- **WHEN** provider 删除失败或删除结果无法确认
- **THEN** 系统 SHALL 保留文件的配额占用，不得提前扣减 `used_bytes`，并记录可重试状态

#### Scenario: Provider deletion and ledger update commit
- **WHEN** provider 删除已确认且数据库事务成功提交
- **THEN** 文件 SHALL 进入不可用终态，关联租户和应用/空间配额 SHALL 恰好释放一次

### Requirement: File deletion terminal retention
文件删除完成后，系统 SHALL 在配置的保留期内保留最少的文件终态、实际大小、配额范围和删除结果信息；普通文件列表、下载和授权查询 SHALL 排除该终态。清理终态记录 SHALL 不得再次触发配额扣减。

#### Scenario: Deleted file is queried through data plane
- **WHEN** 调用方查询已删除文件或按状态列举文件
- **THEN** 文件接口 SHALL 按可见性规则返回不存在或排除该文件，不得泄露内部删除证据
