## ADDED Requirements

### Requirement: Active quota management uses tenant and application scopes
新建、调整和公开展示的配额 SHALL 仅使用 tenant 或 application 业务范围。storage-space scope SHALL 仅作为只读迁移兼容状态存在，不得用于新分配或要求用户选择空间。

#### Scenario: Application quota is displayed
- **WHEN** 用户查看应用详情
- **THEN** 系统 SHALL 按 application_id 返回该应用配额和用量，无需 storage-space ID 输入

