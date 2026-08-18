## ADDED Requirements

### Requirement: Quota and deletion provenance chain
系统 SHALL 将文件入库、配额 reservation、provider 验证、文件可用、删除意图、provider 删除结果和配额释放关联到同一条可追踪 provenance 链。公开响应不得包含凭证、完整物理 key 或授权证据，但受控审计查询 SHALL 能按文件、入库记录或 reservation 定位每次状态变化。

#### Scenario: Successful file is later deleted
- **WHEN** 一个已提交文件随后完成删除
- **THEN** 系统 SHALL 能从审计记录还原其实际大小、结算、删除确认和配额释放结果

#### Scenario: Reconciliation isolates an unknown object
- **WHEN** 共享 S3 对象无法唯一映射到有效租户、应用和命名空间
- **THEN** 系统 SHALL 记录隔离对象及原因，不得创建可用文件或计入任何配额
