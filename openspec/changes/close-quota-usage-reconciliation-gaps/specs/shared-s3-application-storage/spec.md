## ADDED Requirements

### Requirement: Shared namespace inventory for quota statistics
共享 Bucket 的对账 SHALL 按服务端派生的租户/应用/存储空间命名空间扫描对象，并将每个对象分类为已登记有效对象、数据库缺失对象、S3 缺失对象、大小漂移对象、重复映射对象或无法确认归属对象。扫描 SHALL 使用平台配置的 Bucket 和 path-style 规则，调用方不得提供扫描目标。

#### Scenario: Namespace contains an orphan object
- **WHEN** 共享 Bucket 中存在无法映射到 active tenant/application/storage-space 的对象
- **THEN** 对账任务 SHALL 报告该对象为隔离对象，不得计入任何配额或文件列表

#### Scenario: Database file is missing from provider
- **WHEN** 数据库存在可用文件记录但共享 S3 中找不到对应对象
- **THEN** 对账任务 SHALL 报告 provider 缺失并将统计状态标记为存在差异，不得静默继续作为完全一致
