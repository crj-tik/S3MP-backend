## 1. 身份上下文与凭据回收

- [x] 1.1 抽取并复用 session token 的单向 digest helper；会话创建和认证 middleware 使用同一算法，且测试断言原始 token 不入库、不入日志。
- [x] 1.2 修正 session provider：按 digest 查询后校验 session、principal、membership 的撤销/启用/到期及当前 authorization version；为失效情形返回注册的 401 错误。
- [x] 1.3 扩展 PrincipalContext 与 binding 查询，使 API key 产生明确的 application subject，而非伪造 membership；为人和应用分别验证有效 RoleBinding。
- [x] 1.4 以 authorization version 为缓存键/失效条件，补 session 撤销、成员暂停、策略变更与 application 禁用的集成测试。

## 2. 统一文件授权命令

- [x] 2.1 完成 AuthorizedFileCommand 工厂：解析 tenant-owned storage space、canonical relative key、绑定、action、root prefix、请求 ID 和完整语义 fingerprint。
- [x] 2.2 将 list/read/delete/object-operation 入口改为接收 PrincipalContext 与授权命令，移除只凭 tenant_id 的外部可达 service 调用链。
- [x] 2.3 将 multipart get/abort/list-parts/create-part/confirm-part/complete 入口改为接收 PrincipalContext 并在每次操作时重验主体和所有权（create_multipart_upload 已改，其余 6 个方法仍用 tenant_id）。
- [x] 2.4 更新路由和 OpenAPI：下载签名仅接受 relative key 或受控 file reference；完整传递 Idempotency-Key 与 If-Match 到 service 层，并使用注册的稳定错误码。

## 3. MinIO 验证与 multipart 生命周期

- [x] 3.1 扩展对象存储 port 和 MinIO adapter，声明并实现 create/list-part/complete/abort multipart、provider upload ID、part ETag 与最终 HeadObject 元数据读取。
- [x] 3.2 在单文件上传完成时校验派生 physical key、实际大小、规范化内容类型、checksum 需求和可用的 ETag/version；不匹配时不得创建可用文件。
- [x] 3.3 在 multipart 完成时校验 provider session、part 清单与最终对象元数据；实现过期/失败会话的 Abort 和可重试清理状态。
- [x] 3.4 为 provider 不支持的能力、MinIO 错误和"对象成功但数据库提交失败"实现明确的失败/待对账状态，而非报告成功。

## 4. 入库记录、并发与事务

- [x] 4.1 新增修正 ingestion schema 的 Alembic revision：修复带 tenant_id 的 `SET NULL` 复合外键，补 request hash/provider 字段、合适索引及明确的终态保留策略。
- [x] 4.2 实现 ingestion repository 的 begin-or-replay、provider-result、commit-verified、fail-or-quarantine 和 append-event 操作；相同幂等请求复用结果，冲突复用返回 409。
- [x] 4.3 将上传和 multipart 流程改为"先持久化授权意图 → 调用对象存储 → 单事务提交文件/配额/审计/ingestion 终态"，并实现 pending record 对账入口。
- [x] 4.4 在删除与对象变更事务中实现 If-Match 比较；失败不得产生 MinIO 或数据库副作用，并确保审计不记录凭据、物理 key 或完整签名 URL。

## 5. 契约与验证

- [x] 5.1 更新 contracts/OpenAPI、错误目录和示例，反映 canonical relative key、typed application principal、Idempotency-Key、If-Match 与稳定失败语义。
- [x] 5.2 增加 repository、HTTP 与 E2E 回归测试：digest session、application API key、同租户越权、任意 key 下载签名、multipart 接管、过期 Abort、provider 元数据不匹配、幂等冲突和 If-Match 失败。
- [x] 5.3 在本地 Docker PostgreSQL、Redis、MinIO 环境运行 migration、契约校验和完整测试集；记录验证命令及通过结果（`uv run pytest -q --basetemp "$PWD/.tmp-pytest"`：253 passed）。

