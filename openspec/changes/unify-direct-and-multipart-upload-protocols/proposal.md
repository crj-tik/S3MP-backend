## Why

当前文件上传 API 同时暴露代理上传、未完成的直传开关和两段式分片确认，应用无法判断文件内容实际应该发送到哪里；其中 `direct_requested` 没有对应的完整 presigned PUT 响应，分片接口也只登记 ETag 而没有接收分片二进制。需要把应用可见协议收敛为真正可用的直传和分片上传两种模式，并清除旧接口及其契约残留。

## What Changes

- 新增明确的 presigned PUT 直传会话和完成确认响应，应用通过短期 URL 直接写入共享 S3，S3MP 负责最终 HeadObject 校验和入库。
- 将 Multipart 分片上传改为真正接收分片二进制并调用对象存储 `upload_part`，后端自动保存真实 ETag，完成时统一校验并提交。
- 统一两种模式的应用授权、路径派生、配额预留、幂等、审计、过期清理和 ingestion provenance 语义。
- 删除代理完整文件上传接口 `proxy_upload_content` 及其服务端实现。
- 删除 `UploadCreate.direct_requested`，不再通过布尔字段隐式选择未实现的直传能力。
- 删除只登记分片元数据的 `create_multipart_part` 和 `confirm_multipart_part` 接口；由真正的分片上传接口一次完成内容写入和分片记录。
- 清理重复或未接入当前 HTTP 链路的旧 Multipart 应用端口、DTO、测试替身和文档。
- **BREAKING**：更新 `contracts/openapi.yaml`，删除上述旧 paths、operationId、schema、权限目录和示例；契约不得保留已删除接口。
- **BREAKING**：更新前端生成契约，使前端只依赖直传会话和分片会话两套流程。

## Capabilities

### New Capabilities

无。该变更收敛并重构现有文件上传能力，不引入独立的新业务能力。

### Modified Capabilities

- `backend-file-storage`: 将文件写入协议收敛为 presigned PUT 直传和真实二进制 Multipart，删除代理上传与虚假分片确认。
- `backend-api-contract`: 更新运行时与发布 OpenAPI，新增直传/分片响应模型并删除旧路径、operationId、请求模型和字段。
- `backend-application-access`: 统一应用 API Key 对两种上传模式的写入授权和权限范围，不允许绕过应用空间及目录授权。
- `file-ingestion-provenance`: 使直传和分片都在 provider 操作前建立 durable ingestion，并在 provider 验证后才能创建可用文件。
- `api-documentation`: 同步 Swagger 中文接口、参数、响应说明以及上传流程示例，明确应用不接触物理 Bucket Key。

## Impact

- 影响 `src/s3mp/files/api/router.py`、`src/s3mp/files/application/file_service.py`、文件端口和 Multipart 状态机。
- 影响 `src/s3mp/storage/infrastructure/minio.py` 及对象存储端口，需要提供安全的 PUT 签名和真实分片写入能力。
- 影响 PostgreSQL 上传会话、Multipart 分片、配额预留和 ingestion 的状态协调；除非实现确认需要删除废弃字段，否则不通过破坏性迁移清理历史数据。
- 影响 `contracts/openapi.yaml`、运行时 OpenAPI 校验、权限操作目录、中文 Swagger 文档和前端生成类型。
- 影响 HTTP、授权、对象存储、幂等、审计、失败补偿和过期清理测试；必须增加“契约中不存在已删除 operationId/path”的双向断言。
