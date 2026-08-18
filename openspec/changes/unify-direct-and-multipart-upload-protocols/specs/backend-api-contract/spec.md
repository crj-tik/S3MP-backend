## ADDED Requirements

### Requirement: 上传契约只发布直传和分片两种模式
运行时 OpenAPI 与 `contracts/openapi.yaml` SHALL 只发布直传会话和 Multipart 会话两套上传协议。直传响应 SHALL 明确包含会话标识、相对 object key、上传方法、短期 URL、必要请求头和过期时间；Multipart 响应 SHALL 明确包含会话标识、相对 object key、声明大小、状态和分片上传所需信息。契约 SHALL 双向校验实现与基线，并 SHALL 对已删除 path、method、operationId、schema 和权限操作进行负向检查。

#### Scenario: 前端生成直传客户端
- **WHEN** 前端读取发布契约
- **THEN** 契约 SHALL 提供可生成的直传会话、直传完成和直传状态模型，不得要求前端推断 URL 或解析 unknown

#### Scenario: 前端生成分片客户端
- **WHEN** 前端读取发布契约
- **THEN** 契约 SHALL 提供真实分片上传、分片查询、分片完成和中止所需的路径、参数、请求体和响应模型

#### Scenario: 契约包含已删除接口
- **WHEN** 双向契约检查扫描运行时路由与 `contracts/openapi.yaml`
- **THEN** 只要基线或运行时仍包含 `proxy_upload_content`、`create_multipart_part` 或 `confirm_multipart_part` 任一已删除 operationId，检查 SHALL 失败

### Requirement: 上传接口描述与权限目录保持一致
直传和 Multipart 的每个公开操作 SHALL 声明统一的中文用途、参数、状态和错误说明，并 SHALL 使用应用 API Key 可理解且可配置的文件写权限；废弃的代理上传及空分片登记权限不得继续出现在权限操作目录、Swagger、示例或生成类型中。

#### Scenario: 应用读取上传权限说明
- **WHEN** 应用读取 Swagger 或权限目录
- **THEN** 它 SHALL 能区分直传会话、直传完成、分片上传、分片完成和中止操作，且不应看到代理上传权限
