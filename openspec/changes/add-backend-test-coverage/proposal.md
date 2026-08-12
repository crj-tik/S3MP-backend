## Why

后端已通过 OpenSpec 流程完成 4 个 change（建库、契约 API、持久化、修 8 个 bug），现有 22 个测试文件 / 176 用例全绿，但分层严重失衡：19 个纯 domain 单元、仅 3 个 HTTP 测试（其中真正覆盖领域端点的只有 `/me`）、仅 3 个 DB/repository 测试且全属 identity 且用 aiosqlite。契约声明 64 个 operationId 且运行时已对齐，但绝大多数声明操作的"可执行基线"无 HTTP 级证据；横切语义（idempotency 重用、ETag 冲突、`audit_unavailable`）、租户隔离、以及 fix-bugs 修复的 `select_membership` 多 membership 选择都缺针对性回归。更关键的是：现有测试全程不连真实基础设施，后端能否正确连上已部署的 docker 服务（pg/redis/minio）完全没有验证。质量信号网络在金字塔中间断裂——契约、安全与基础设施集成的可观察行为都没有被持续验证。

## What Changes

- 为 6 个 router（identity / authorization / applications / files / governance / storage）补 HTTP 契约测试（fake 注入），对每个声明 operationId 至少验证一条成功路径 + 一条代表性失败路径（401/403/404/409/410/503 之一）。
- 新增真实服务端到端测试层：起 `create_app(真实 S3MP_* 配置)` 注入真实 service + 真实 store + 真实 `MinioObjectStorageAdapter` + 真实 redis，经 HTTP 跑完整链路，验证 adapter 真能连 docker 部署的 pg/redis/minio、文件操作真实落地、readiness 真实探活。
- 为 fix-bugs 修复的 `select_membership`（`break`→`continue`）补针对性回归：构造同一租户 `[suspended, active]` 两条 membership，断言跳过 suspended 返回 active。
- 补租户隔离 HTTP 证据：跨租户 PrincipalContext 请求他租户资源，断言 `404 resource_not_found` 且响应不泄露他租户存在性。
- 补横切语义 HTTP 级验证：Idempotency-Key 重用 → `409 idempotency_key_reused` 且不重复执行；过期 If-Match → ETag 冲突错误码；audit 持久化失败的高风险 mutation → `503 audit_unavailable` 且不触发外部存储动作。
- 为 `files` / `applications` / `storage` / `governance` 的 SQLAlchemy repository 补真实 postgresql 持久化测试，连 `s3mp` 主库（测试环境），重点验证 tenant-scoped 查询（跨租户返回 None）与 CRUD 往返。
- 迁移 3 个现有 aiosqlite 测试（`test_identity_repository` / `test_identity_constraints` / `test_migrations`）到真实 postgresql，移除 aiosqlite 依赖。
- 为 `scripts/check_openapi.py` 的"基线→运行时"反向检查分支补单测，构造基线多出端点的临时 OpenAPI 断言退出码非 0。
- 持久化与集成测试连真实 docker 服务；HTTP 契约层 fake 与真实端到端并存；不新增共享 conftest。

## Capabilities

### New Capabilities

无。本 change 仅补充测试覆盖，不引入新能力。

### Modified Capabilities

无。所有被验证的行为（租户隔离、多 membership 选择、契约可执行性、横切语义、审计闭门、基础设施连通性）已在现有 6 个 capability spec 中声明；本 change 不改变任何 spec 级行为，故 opt out of specs（`.openspec.yaml` 设 `skip_specs: true`）。

## Impact

- 新增 `tests/**` 下的 HTTP 契约测试、真实端到端测试、repository 测试、回归测试与契约脚本单测；迁移 3 个现有 aiosqlite 测试到真实 postgresql；不修改 `src/**` 生产代码、不修改 `contracts/**`、不修改 `migrations/**`。
- 移除 `aiosqlite` dev 依赖；复用 pytest 8.3 + pytest-asyncio 0.25（auto 模式）+ httpx AsyncClient + ASGITransport + 真实 docker 服务。
- 持久化与集成测试连真实 docker 服务（pg@18110 / redis@18113 / minio@9000），docker 必须运行；HTTP 契约层 fake 保留、真实端到端并存。
- 需修正 `deploy/secrets/database_url`（当前 `s3mp` 用户不存在，改用 `postgresql+asyncpg://platform_pg_admin:Bk-Skill@localhost:18110/s3mp`，与 `alembic.ini` 一致）与 `deploy/.env` 的 `S3MP_REDIS_URL`（当前端口 6379 错且缺密码，改 `redis://:Bk-Skill@localhost:18113/0`）；`S3MP_S3_*` 已正确。
- 迁移往返测试直接在 `s3mp` 库跑，`downgrade base` 会清空表后 `upgrade head` 重建（测试环境可接受）。
- 预期测试用例数从 176 增长到约 280+，因含真实 IO 运行时长会增长，但单机可接受。
