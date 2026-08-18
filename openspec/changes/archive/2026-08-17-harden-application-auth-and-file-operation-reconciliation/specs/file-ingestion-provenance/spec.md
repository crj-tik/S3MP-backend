## MODIFIED Requirements

### Requirement: Verified commit and provenance events
系统 SHALL 仅在 provider metadata 已根据获授权命令验证且当前主体仍有权执行该写入时，将 ingestion record 转换为 committed。它 SHALL 持久化 provider ETag/version（可用时）、实际大小、实际内容类型、请求 checksum 验证结果，以及每个终态或安全相关转换的追加事件。恢复任务 SHALL 重查 acting principal、application/API Key 状态（如适用）、authorization version、storage space 和 canonical relative key 的当前权限，而非只信任创建时证据。

#### Scenario: Provider object matches the authorized upload
- **WHEN** 对象 provider 报告的 key、大小、内容类型、checksum 要求和 multipart 完成状态均与获授权命令匹配，且当前授权仍有效
- **THEN** 系统 SHALL 原子地使文件可用、将 ingestion record 标记为 committed，并追加 committed 事件

#### Scenario: Provider object fails verification
- **WHEN** provider metadata 缺失或与获授权命令不同
- **THEN** 系统 SHALL 不得使文件可用，SHALL 标记 ingestion record 为 failed 或 quarantined，并追加记录非敏感验证原因的事件

#### Scenario: 恢复前权限已撤销
- **WHEN** 对象已由 provider 接收但数据库恢复任务开始前，acting principal、application、API Key 或资源范围已失效
- **THEN** 系统 SHALL 不得提交文件，SHALL 记录安全原因，并将对象安排为隔离或受控清理

### Requirement: Referentially valid retention and cleanup
ingestion schema SHALL 在 upload-session 或 file 清理期间保持 tenant integrity。删除策略 SHALL NOT 尝试将非空 tenant identifier 设为 NULL，且 terminal provenance SHALL 在配置保留期内保持可查询。待协调 ingestion 和待删除记录 SHALL 被调度的恢复机制自动尝试收敛，并在不可恢复时留下可查询终态。

#### Scenario: An upload session is cleaned up
- **WHEN** 一个过期或中止的 upload session 被删除
- **THEN** 数据库 SHALL 在不违反外键或 NOT NULL 约束的情况下完成删除，并按明确保留策略保留或移除关联 ingestion record

#### Scenario: 数据库故障后的 provider 成功
- **WHEN** provider 成功完成对象写入但记录最终状态的数据库事务失败
- **THEN** 恢复机制 SHALL 自动重新验证并最终提交、隔离或清理该对象，且不得无限期保持未处理状态
