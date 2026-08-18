## ADDED Requirements

### Requirement: Swagger 明确呈现两种上传流程
Swagger 和发布契约 SHALL 使用一致的中文描述说明直传与 Multipart 的调用顺序、应用相对路径、鉴权头、幂等头、二进制请求体、完成确认和错误语义。文档 SHALL 明确应用不接触共享 Bucket、物理 object key、S3 凭证或 provider upload ID。

#### Scenario: 应用开发者查看直传接口
- **WHEN** 开发者打开 Swagger
- **THEN** 文档 SHALL 能直接看出先创建会话、再向 presigned URL PUT、最后调用 S3MP 完成确认

#### Scenario: 应用开发者查看分片接口
- **WHEN** 开发者打开 Swagger
- **THEN** 文档 SHALL 能直接看出创建会话、PUT 每个分片二进制、查询分片、完成或中止的完整顺序

#### Scenario: 开发者查看已删除接口
- **WHEN** 开发者读取 Swagger 或 `contracts/openapi.yaml`
- **THEN** 不得看到代理上传、空分片登记或独立 ETag 确认接口
