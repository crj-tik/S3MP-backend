## MODIFIED Requirements

### Requirement: Durable ingestion lifecycle record
系统 SHALL 在请求对象 provider 执行上传或 multipart 完成前创建租户范围的入库记录。记录 SHALL 保留 application_id、稳定应用命名空间、授权的 relative key、派生共享 Bucket/physical key、storage space、acting/creator principals、authorization version、配额 reservation、请求标识、幂等身份和明确生命周期状态。

#### Scenario: Authorized application upload is initiated
- **WHEN** 已认证 application principal 成功发起授权上传或 multipart 上传
- **THEN** 系统 SHALL 在返回 provider 指令或接受内容前持久化一条 initiated 入库记录和容量 reservation

#### Scenario: Same application retries with idempotency key
- **WHEN** 同一应用使用相同幂等键和等价语义重试
- **THEN** 系统 SHALL 返回原入库结果，不得创建第二条记录或重复 reservation

#### Scenario: Authorized upload is initiated
- **WHEN** 已认证主体成功发起授权上传或 multipart 上传
- **THEN** 系统 SHALL 在返回 provider 指令或接受内容前持久化一条 initiated 入库记录

#### Scenario: A retry uses the same idempotency identity
- **WHEN** 同一认证主体使用相同幂等键和等价请求语义重试
- **THEN** 系统 SHALL 返回原入库结果，不得创建第二条入库记录

### Requirement: Verified commit and provenance events
系统 SHALL 仅在 provider 元数据与授权命令的 tenant、application namespace、physical key、大小、类型、校验和及 multipart 完成状态一致后将入库置为 committed。系统 SHALL 持久化实际大小、reservation 结算结果和非敏感授权来源事件。

#### Scenario: Provider object belongs to the authorized application
- **WHEN** provider 返回的对象与授权应用 namespace、Key 和元数据一致
- **THEN** 系统 SHALL 原子地使文件可用、标记入库 committed、确认容量使用量并追加 committed event

#### Scenario: Provider object has an unrecognized namespace
- **WHEN** provider 对象无法映射到唯一租户和应用
- **THEN** 系统 SHALL 不得使其可用或计入配额，并 SHALL 标记 failed/quarantined

#### Scenario: Provider object matches the authorized upload
- **WHEN** provider 返回的对象 whose key、大小、类型、校验和和 multipart 状态与授权命令一致
- **THEN** 系统 SHALL 原子地使文件可用、标记入库 committed，并追加 committed event

#### Scenario: Provider object fails verification
- **WHEN** provider 元数据缺失或与授权命令不一致
- **THEN** 系统 SHALL 不得使文件可用， SHALL 标记 failed 或 quarantined，并追加非敏感失败原因事件

### Requirement: Ingestion enum filters
入库记录和入库事件查询 SHALL 使用目录中的 ingestion status 与 event type 枚举；入库记录列表 SHALL 支持 `status`，事件列表 SHALL 支持 `event_type`。筛选条件 SHALL 传递到服务和仓储层，并 SHALL 限定当前租户、应用和授权命名空间。

#### Scenario: Ingestion records are filtered
- **WHEN** 管理员按目录中的入库状态或事件类型查询
- **THEN** 系统 SHALL 返回真实匹配的记录，并保持分页游标和租户/应用隔离

#### Scenario: Unknown ingestion enum is submitted
- **WHEN** 请求提交未知入库状态或事件类型
- **THEN** 系统 SHALL 返回 `422 validation_failed`，不得返回全量结果
