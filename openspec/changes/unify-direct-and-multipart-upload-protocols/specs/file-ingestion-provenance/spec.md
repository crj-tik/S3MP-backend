## ADDED Requirements

### Requirement: 两种上传模式共享入库事实链
直传和 Multipart SHALL 在 provider 写入或完成之前创建 tenant-scoped ingestion 记录，并保存授权的 relative key、派生 physical key、storage space、主体、authorization version、请求标识和幂等身份。只有在 provider 元数据通过验证后，系统 SHALL 原子地将文件标记为可用并记录 provider ETag/version、实际大小、实际类型和摘要结果。

#### Scenario: 直传会话建立 provenance
- **WHEN** 系统成功签发直传 URL
- **THEN** 系统 SHALL 先持久化 initiated ingestion，再返回 provider instruction

#### Scenario: Multipart 分片失败
- **WHEN** 某个分片或最终 complete 失败
- **THEN** 系统 SHALL 保留可追踪的 ingestion 失败或隔离状态，且 SHALL 不创建可用 FileObject

#### Scenario: 重试同一上传
- **WHEN** 同一主体使用相同幂等身份重试等价的直传会话或 Multipart 会话
- **THEN** 系统 SHALL 返回原有结果，不得重复创建 provider session 或 ingestion 记录
