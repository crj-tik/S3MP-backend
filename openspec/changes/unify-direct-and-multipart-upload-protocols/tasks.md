## 1. 契约与权限基线

- [x] 1.1 在运行时 DTO 中定义 `DirectUploadCreate`、`DirectUploadSessionRuntime`、直传完成响应和明确的 Multipart 会话/分片响应模型，移除 `UploadCreate.direct_requested`
- [x] 1.2 更新上传权限操作目录，统一直传和 Multipart 的应用写入授权，并删除代理上传、空分片登记和旧 ETag 确认操作
- [x] 1.3 为新增和保留的上传接口补齐一致的中文 operation、参数、请求体、响应体、错误和安全说明
- [x] 1.4 在契约校验工具中增加已删除 operationId/path/schema 的负向断言，覆盖 `proxy_upload_content`、`create_multipart_part`、`confirm_multipart_part`

## 2. 直传端到端实现

- [x] 2.1 为对象存储端口增加受限的 presigned PUT 能力，只接受服务端派生的 `ProviderTarget`、Content-Type 和有限 TTL
- [x] 2.2 实现直传会话创建：canonical relative key、应用边界、目录授权、Key scope、配额、幂等和 ingestion 记录必须在返回 URL 前完成
- [x] 2.3 实现直传状态查询和完成确认，复用 HeadObject、checksum、Content-Length、Content-Type、授权重验证和 FileObject 入库逻辑
- [x] 2.4 确保直传响应只返回短期 provider instruction 和相对 object key，不返回 Bucket、physical key、provider upload ID 或凭证
- [x] 2.5 实现直传过期、重复完成、provider 缺失、元数据不匹配和完成后数据库失败的失败状态及补偿路径

## 3. Multipart 真实分片实现

- [x] 3.1 将 Multipart 创建流程固定为应用可见的 `multipart.manage` 或统一写权限语义，并返回稳定的 part size、会话状态和过期时间
- [x] 3.2 将 `PUT /multipart_uploads/{multipart_id}/parts/{part_number}` 改为接收原始二进制和 Content-Length，完成会话/主体/空间/路径授权后调用 `ObjectStorage.upload_part`
- [x] 3.3 保存 provider 返回的真实 ETag、分片编号和实际长度，重复上传同一编号时使用幂等语义而不是信任客户端 ETag
- [x] 3.4 保留分片列表查询，返回已由服务端确认的分片结果，并禁止泄露 provider upload ID
- [x] 3.5 完善 Multipart completion：校验分片连续性、去重、总长度、数据库 ETag、provider inventory、最终对象元数据和 ingestion commit
- [x] 3.6 完善 Multipart abort、过期清理、provider abort 失败和 reconciliation_required 状态，确保不会遗留不可追踪的 provider upload

## 4. 删除旧协议和重复实现

- [x] 4.1 删除 `proxy_upload_content` 路由、服务方法、应用端口、权限映射和相关错误/示例引用
- [x] 4.2 删除 `create_multipart_part` 路由及 `MultipartPartCreate` 请求模型
- [x] 4.3 删除旧的 `confirm_multipart_part` 空确认语义及 `MultipartPartConfirm` 请求模型，将同一路径改为真实二进制上传并使用新的 operationId/响应模型
- [x] 4.4 删除 `direct_requested` 在路由、服务、持久化 payload、幂等 fingerprint、测试和 OpenAPI 中的所有引用
- [x] 4.5 合并或清理未接入当前 HTTP 链路的旧 Multipart domain/application service，保证只有一套 Multipart 状态和 provider 调用路径

## 5. 持久化、配额与 provenance

- [x] 5.1 审核 upload_session、multipart_session、multipart_part、quota reservation 和 ingestion 字段，确认新流程所需约束、唯一键、状态和索引完整
- [x] 5.2 如确有新字段或约束，新增可回滚数据库迁移；不删除历史数据，不通过迁移清理既有上传事实（0030、0031）
- [x] 5.3 验证直传和 Multipart 都在 provider 操作前持久化 ingestion，并在 committed、failed、quarantined、reconciliation_required 状态下记录非敏感原因
- [x] 5.4 验证配额预留、实际大小结算、失败释放和重复请求不会产生重复预留或负数使用量

## 6. OpenAPI 与前端契约收敛

- [x] 6.1 从运行时路由移除旧接口后重新生成运行时 OpenAPI，确认只存在直传和 Multipart 两种上传协议
- [x] 6.2 同步 `contracts/openapi.yaml`：新增直传路径、响应 schema、真实分片请求/响应 schema，并删除旧 paths、operationId、schema、字段和权限条目
- [x] 6.3 对运行时 OpenAPI 与发布契约执行双向比较，明确验证“基线多出的已删除接口”和“运行时多出的未发布接口”均会失败
- [x] 6.4 更新 Swagger 中文文档和上传示例，明确应用使用相对路径、presigned URL、原始分片二进制和完成确认
- [x] 6.5 输出前端迁移说明：小文件走直传，大文件走 Multipart；删除对代理上传、`direct_requested`、空分片登记和客户端 ETag 确认的依赖

## 7. 测试与安全验证

- [x] 7.1 增加直传 HTTP 测试：签发 URL、错误 TTL、越权路径、Key scope、完成校验、checksum、幂等和吊销后完成
- [x] 7.2 增加 Multipart HTTP 测试：真实二进制分片、ETag 持久化、重复分片、跨会话访问、分片列表、完成、abort 和过期清理
- [x] 7.3 增加对象存储适配器测试：path-style、presigned PUT、upload_part、complete、abort、provider 错误和返回元数据校验
- [x] 7.4 增加 ingestion、配额、审计和 reconciliation 失败场景测试，确认 provider 成功但数据库失败时不会产生可用脏文件
- [x] 7.5 增加契约负向测试，确保全仓不存在已删除 operationId、旧路径、`direct_requested` 和旧请求 schema 引用
- [ ] 7.6 运行全套 Ruff、Mypy、pytest、OpenAPI 覆盖率和 OpenSpec strict validation，并记录容器级 MinIO/PostgreSQL 验收结果

## 8. 发布与清理验收

- [ ] 8.1 检查前端生成代码和本地 mock 已切换到新契约，确认不再调用旧上传接口
- [ ] 8.2 在 MinIO 和生产兼容 S3 上分别验证直传、Multipart、path-style、共享 Bucket 命名空间和下载回读
- [x] 8.3 部署前确认旧接口从 Swagger、路由、权限目录、契约、示例和日志中全部消失
- [ ] 8.4 更新 change 任务、同步主规格，确认实现与契约完全一致后再归档
