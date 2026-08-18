## Context

当前应用服务已经具备共享 Bucket、服务端派生物理 Key、provider multipart 端口和 ingestion 校验能力，但 HTTP 层仍混合了代理完整上传、未兑现的 `direct_requested` 开关，以及“登记分片/确认 ETag”两步接口。对象存储适配器已有 provider 分片上传能力，直传则需要补齐当前应用服务可调用的 PUT 签名端口。

## Goals / Non-Goals

**Goals:**

- 让应用可见上传协议只有 presigned PUT 直传和服务端管理的真实二进制 Multipart。
- 让两种模式都经过同一套应用身份、storage space、目录授权、配额、幂等、审计和 ingestion provenance 校验。
- 从运行时路由、权限目录、Swagger、发布 OpenAPI、测试和示例中彻底删除代理上传及空分片登记接口。
- 让契约双向检查能够发现“已删除接口仍残留在契约”这一类回归。

**Non-Goals:**

- 不改变共享 Bucket、应用 storage namespace 或相对 object key 的路径模型。
- 不向应用暴露 Bucket、物理 object key、S3 凭证或 provider upload ID。
- 不在本次变更中删除历史上传会话或 ingestion 数据；历史数据按现有过期和保留策略处理。
- 不实现浏览器 SDK 或前端页面，只提供稳定后端契约和可测试的 HTTP 行为。

## Decisions

### 1. 直传使用独立、明确的会话接口

新增：

```text
POST /api/v1/storage_spaces/{space_id}/direct_uploads
GET  /api/v1/direct_uploads/{upload_id}
POST /api/v1/direct_uploads/{upload_id}/completion
```

创建请求使用 `DirectUploadCreate`，只包含相对 `object_key`、`content_length`、`content_type` 和可选 checksum。响应使用 `DirectUploadSessionRuntime`，包含 `id`、相对 key、`mode=direct`、`method=PUT`、短期 `url`、安全的必要 headers 和 `expires_at`。

URL 由对象存储端口根据服务端派生的 `ProviderTarget` 签发，API Key、Bucket 和 provider key 不进入响应。完成接口仍要求 S3MP API Key，并复用现有 HeadObject、ingestion revalidation 和 commit 流程。

选择独立路径而不是继续复用 `uploads`，是为了让客户端无需读取隐藏的 mode 字段，也避免旧的代理上传语义被误认为仍然可用。保留 `direct_requested` 的替代方案被否决，因为布尔字段不能表达 provider instruction，也无法解决当前缺少 presigned PUT 响应的问题。

### 2. Multipart 的单个 PUT 接口同时完成“上传+确认”

保留 Multipart 会话、状态查询、分片查询、完成和中止，删除两个空操作接口，改为：

```text
PUT /api/v1/multipart_uploads/{multipart_id}/parts/{part_number}
```

该接口接收原始二进制 body 和 `Content-Length`，应用服务重新验证会话及路径授权后调用 `ObjectStorage.upload_part(target, provider_upload_id, part_number, body)`，使用 provider 返回的 ETag 和实际长度写入 `multipart_part`。响应使用明确的 `MultipartPartRuntime`。

这样不会信任客户端声明的 ETag；completion 只接受服务端已保存的 part 结果，并继续校验顺序、去重、总大小、provider inventory 和最终对象。

选择后端代理分片而不是向应用返回每片的 provider presigned URL，是因为当前目标是隐藏 S3/MinIO 细节、复用现有授权和审计链路，并且对象存储端口已经具备 `upload_part`。未来如需大规模浏览器直连，可另开 change 增加“直传分片 URL”模式，不与本次协议混合。

### 3. 两种模式共享授权和应用写权限

直传会话、直传完成、Multipart 会话、分片、完成和中止都使用同一 application context、storage space 和 canonical relative key 校验。对第三方应用公开的写权限统一为 `files.write`；`multipart.manage` 不再作为应用必须理解的独立业务权限，内部实现可继续在审计或服务层标识操作类型。

直传 URL 签发时记录授权证据；完成时重新校验主体、Key 状态、应用状态、空间状态和 authorization version。Multipart 的每个分片也重新校验会话归属，避免只在创建会话时授权一次。

### 4. 复用 ingestion 与幂等，不重建状态机

直传会话和 Multipart 会话都先创建 durable ingestion，再返回 provider instruction 或接受 provider 写入。重复的等价请求返回原结果；同一幂等键对应不同 key、大小、类型、checksum 或分片语义时返回冲突。provider 校验失败进入 failed 或 reconciliation_required，不创建可用 `FileObject`。

### 5. 契约删除采用“运行时和基线双向负向断言”

实现完成后生成运行时 OpenAPI，与 `contracts/openapi.yaml` 双向比对：

- 新接口、请求模型、响应模型和 operationId 必须双向存在；
- `proxy_upload_content`、`create_multipart_part`、`confirm_multipart_part` 及其旧 schema 必须双向不存在；
- `direct_requested` 不得出现在 Upload 请求 schema、示例或生成结果；
- 权限操作目录、中文 descriptions、错误码和测试替身不得引用已删除 operationId。

### 6. 只在必要时做数据库迁移

现有 `upload_session`、`multipart_session`、`multipart_part`、quota reservation 和 ingestion 表仍然承载新流程，因此默认不删除表或历史列。实现时只检查并补足分片上传所需的约束、真实 ETag、内容长度和状态字段；如果确认某些字段只服务于已删除代理协议，先通过代码停止写入，再另行制定数据迁移，而不是在本 change 中无审阅删除历史数据。

## Risks / Trade-offs

- [Risk] Presigned URL 在有效期内可能脱离 API Key 独立使用 → 使用短 TTL、固定派生 Key、限制 PUT 方法和 Content-Type；完成接口始终重新认证和校验，吊销 API Key 不承诺立即撤销已签发 URL。
- [Risk] Multipart 代理分片会占用 API 带宽和服务端内存 → 使用流式 request body 或受控分片大小上限，不使用无限制 `bytes` 缓冲；把大文件阈值、最小/最大 part size 做成服务端配置。
- [Risk] 删除旧接口会导致旧前端立即失败 → 这是明确的 breaking change，先更新发布契约和前端生成客户端，再部署 API；不提供旧路径兼容别名，避免契约和实现继续双轨。
- [Risk] provider 分片已写入但数据库记录失败 → 将 ingestion 标为 reconciliation_required，保留 provider upload ID 的内部记录，并由清理/补偿任务执行 abort 或重试。
- [Risk] 直传完成时对象已写入但调用方断线 → completion 具备幂等性，后台 reconciliation 根据 durable ingestion 查询并完成或隔离，不依赖客户端再次创建会话。

## Migration Plan

1. 先实现新直传和真实 Multipart 路由、服务端口、DTO、授权和 ingestion 流程，并同步运行时 OpenAPI。
2. 删除代理上传、空分片登记和旧确认路由、服务方法、权限目录和测试替身。
3. 从 `contracts/openapi.yaml` 删除旧 paths、operationId、schema、参数和 `direct_requested`，新增明确的直传/分片模型。
4. 执行运行时契约双向比较、OpenSpec 校验、HTTP 安全测试、对象存储集成测试和失败补偿测试。
5. 前端切换到两套新流程后部署 API；检查旧 operationId 在代码、契约、文档和生成物中全仓为零。

回滚时只能回滚到新 change 的上一版本部署，不恢复已删除的公开路径作为兼容别名；如果需要兼容旧客户端，必须在发布前另行批准一个有明确截止日期的兼容 change。
