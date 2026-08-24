## ADDED Requirements

### Requirement: File authorization is configured by application and directory
文件权限的公开授权模型 SHALL 允许管理员选择应用和可选 canonical directory prefix。系统 SHALL 在内部将应用解析为其唯一存储记录，前端不得要求管理员选择 storage space。

#### Scenario: Administrator grants application file access
- **WHEN** 管理员为主体选择应用并授予 `files.read`，可选指定目录前缀
- **THEN** 系统 SHALL 将授权绑定至该应用的唯一内部 namespace，并在响应中展示应用和目录范围

