## ADDED Requirements

### Requirement: Public contract exposes implicit application storage
OpenAPI SHALL 在应用创建、列表和详情响应中声明只读存储摘要，并 SHALL 提供以应用上下文执行文件操作和配置目录授权的契约。契约 MUST NOT 发布创建、绑定、解绑或选择 storage space 的业务操作。

#### Scenario: Frontend regenerates its API client
- **WHEN** 前端从发布契约重新生成类型
- **THEN** 生成客户端 SHALL 能直接读取应用存储摘要和调用应用文件接口，且不存在 create-storage-space 操作

#### Scenario: Application is created
- **WHEN** 客户端提交应用名称和允许的授权代表信息
- **THEN** 创建响应 SHALL 包含已经可用的只读存储摘要，且请求中不包含任何存储选择字段

