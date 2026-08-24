## ADDED Requirements

### Requirement: Public file operations use application context
面向业务调用方的文件列举、上传、下载、multipart 和对象变更接口 SHALL 以当前租户内的 application_id 或已认证 application principal 确定唯一存储上下文，不得要求调用方从 storage-space 候选中选择目标。

#### Scenario: Human opens an application file browser
- **WHEN** 已授权成员打开某应用的文件页面
- **THEN** 系统 SHALL 自动解析该应用唯一存储上下文并返回文件，不要求 storage-space 选择步骤

#### Scenario: Application key performs an operation
- **WHEN** application API Key 发起文件操作
- **THEN** 系统 SHALL 仅使用该 Key 绑定应用的内部存储上下文，并拒绝调用方覆盖目标应用或 namespace

