## Context

See proposal.md — Why. 后端已实现 64 个声明操作，运行时路由与契约双向对齐（`scripts/check_openapi.py` 已校验），但测试金字塔中间断裂：19 个 domain 单元、3 个 HTTP（领域端点仅 `/me`）、3 个 DB 测试（全属 identity，且用 aiosqlite）。更关键的是现有测试全程不连真实基础设施——后端能否连上已部署的 docker 服务（pg/redis/minio）无任何验证。被验证的可观察行为（租户隔离、多 membership 选择、契约可执行性、idempotency/ETag/audit 横切语义、基础设施连通性）在现有 6 个 capability spec 中已声明，缺的是持续验证它们的测试信号。约束：pytest-asyncio auto 模式、Protocol-based fake（不用 `unittest.mock`）、不引入共享 conftest。本次变更：持久化与集成测试连真实 docker 服务（docker 必运行），HTTP 契约层 fake 与真实端到端并存，移除 aiosqlite。

配置核实结论（docker 已验证可连）：
- pg：`postgresql+asyncpg://s3mp_app:bk-s3mp-backend@localhost:18110/s3mp`（与 `alembic.ini` 一致；`s3mp` 用户不存在，须改 `deploy/secrets/database_url`）；`s3mp` 库已迁移 30 张表。
- redis：`redis://:Bk-Skill@localhost:18113/0`（须改 `deploy/.env`：端口 6379→18113、加密码 `Bk-Skill`）。
- minio：`http://localhost:9000`，bucket `s3mp-dev`，AK `s3mp-app` / SK `bk-s3mp-backend`，path-style（`deploy/.env` 的 `S3MP_S3_*` 已正确）。

## Goals / Non-Goals

**Goals:**
- 把金字塔中间补实：HTTP 契约层从 3 文件扩到覆盖 6 个 router 的代表性路径。
- 新增真实服务端到端层：验证后端真能连上 docker 部署的 pg/redis/minio、文件操作真实落地、readiness 真实探活。
- 为已修过的 `select_membership` bug 与 8 个 fix-bugs 修复点补针对性回归，防止回归。
- 把横切语义（idempotency / ETag / audit_unavailable）与租户隔离从 domain 层提升到 HTTP 层有可观察证据。
- 持久化层覆盖从 identity 扩到 files/applications/storage/governance，连真实 postgresql 验证 tenant-scoped 查询。
- 移除 aiosqlite，持久化与迁移测试统一连真实 postgresql。

**Non-Goals:**
- 不追求覆盖率数字指标；以风险驱动选择验证点。
- 不改任何 spec 行为、不改契约、不改迁移。
- 不引入共享 conftest（项目约定 fixture 局部定义，除非有充分理由）。
- 不做全量 64 操作的逐条 HTTP 测试；每个 operationId 至少一条成功 + 一条代表性失败即可。
- 不加 opt-in 机制（marker / `--run-integration` / skip）——docker 一定启动，pytest 一条命令全跑。
- 不引入独立测试库——直接用 `s3mp` 主库（测试环境）。

## Decisions

### 1. HTTP 层双轨：fake 契约层 + 真实端到端层并存

两套 HTTP 测试回答不同问题，互补不替代：

```
┌─────────────────────────────────────────────────────────────────┐
│  fake 契约层（快、确定）           真实端到端层（慢、真）        │
│  create_app(Settings())            create_app(真实 S3MP_* 配置) │
│  fake service 注入 app.state       真实 service + 真实 store +  │
│  fake 返回固定 DTO / 抛 ApiError    真实 MinioObjectStorageAdapter│
│  验证：路由存在?错误码翻译?         验证：真能连 docker?IO 落地? │
│  覆盖：6 router 成功+失败路径       覆盖：完整链路 + readiness    │
└─────────────────────────────────────────────────────────────────┘
```

fake 层用 `create_app(Settings())`（config 全 None，store 是 `_NoopStore`，但测试把整个 service 替换成 fake），验证契约翻译与错误码。真实端到端层用 `create_app(Settings(database_url=..., redis_url=..., s3_endpoint=...))`，lifespan 装配真实 store + 真实 `MinioObjectStorageAdapter`，PrincipalContext 经中间件注入，跑完整 HTTP→service→store/adapter→真实服务链路。

**备选**：只用真实端到端、砍掉 fake。**否决**——fake 层快、确定、可注入任意故障（audit 失败、idempotency 重用），这些在真实链路里难稳定构造；fake 层覆盖契约边界，真实层覆盖连通性，职责正交。

### 2. fake service 用 Protocol-based 鸭子类型，按 router 分文件定义

每个 router 的 fake 实现对应 application service 的方法子集，返回固定 DTO 或抛 `ApiError`。fake 不共享、不继承基类。例如 `identity_management` fake 实现 `list_users`/`get_user`/`create_member` 等；`api_key_service` fake 实现 issue/rotate/revoke 并对 secret 二次查询返回 `410`。

**备选**：用 `unittest.mock.AsyncMock` 自动生成。**否决**——项目约定不用 mock 库替代领域端口；显式 fake 让"被调用次数"成为可读的测试信号。

### 3. HTTP 测试复用 `test_identity_security.py` 注入模板，不引入新机制

fake 层每个测试用 `create_app(Settings())` 起应用，经 `app.state.<service>` 注入 fake，经 `@app.middleware("http")` 把 `select_membership([...])` 构造的 PrincipalContext 塞进 `request.state.principal_context`，再用 `httpx.AsyncClient` + `ASGITransport` 发请求。真实层复用同一模板，仅把 `Settings()` 换成真实配置、不注入 fake（用 lifespan 装配的真实 service）。

**备选**：引入共享 `conftest.py` 提供 fixture。**否决**——项目约定无共享 conftest，各 router fake 形状不同，共享反而增加耦合。

### 4. 风险驱动优先级：P0 回归 + 契约基线 → P1 横切 → P2 持久化 → P3 真实端到端 → P4 脚本单测

P0 先做：护住已修 bug（`select_membership`）与契约可执行基线（fake HTTP 覆盖）。P1 做安全/契约错误码的 HTTP 证据。P2 补持久化层（真实 pg）。P3 真实端到端（依赖前几层稳定 + docker 服务可用）。P4 最低。理由：已修 bug 回归风险最高；契约基线是前端硬约束；横切与隔离次之；持久化已被 service 间接覆盖是补强；真实端到端验证连通性放最后（依赖最多）；脚本单测价值最低。

**备选**：按 context 横切。**否决**——横切会推迟 P0 回归。

### 5. 租户隔离 HTTP 证据：构造他租户 PrincipalContext 打本租户资源，断言 404 且不泄露

fake 层注入属于 tenant B 的 PrincipalContext，请求 tenant A 的资源 ID（fake service 对 A 的查询返回 None 模拟跨租户隔离），断言 `404 resource_not_found` 且响应体不含 A 的任何字段。真实层在 pg 中种入 tenant A 数据，用 tenant B context 查询，断言 404。这把 spec `backend-identity-authorization` 的"不泄露该资源是否存在"从 domain 提升到 HTTP 可观察层。

### 6. 横切语义用 fake 注入故障，断言错误码 + 副作用未发生

- idempotency：fake service 记录首次调用的 fingerprint，第二次同 key 不同 body 抛 `409 idempotency_key_reused`；断言 fake 只被调用一次。
- ETag：fake 返回带 ETag 的响应；带过期 `If-Match` 的请求抛冲突错误码。
- audit_unavailable：fake audit store 抛持久化异常；高风险 mutation（copy/move/delete/签发）应返回 `503 audit_unavailable`，且 fake object storage 断言未被调用（fail-close）。

### 7. 持久化测试连真实 postgresql，用 `s3mp` 主库 + 事务回滚隔离

每文件用 `create_engine(TEST_DATABASE_URL)`（真实 pg，与 `alembic.ini` 一致），`AsyncSession(engine, expire_on_commit=False)`。`s3mp` 库已迁移 30 张表，无需 `create_all`。隔离方式：每个测试用 session 开启事务、测试结束 rollback，不持久化测试数据，避免污染库。重点验证：tenant-scoped 查询跨租户返回 None、CRUD 往返、配额结算、FK 约束。

`test_identity_repository.py` 里那条 `PRAGMA foreign_keys` sqlite 专属断言替换为 pg FK 强制测试（种入跨租户链接断言 `IntegrityError`）。

**备选**：保留 aiosqlite 快速层 + 真实 pg 集成层。**否决**——用户明确移除 aiosqlite、直接用 postgresql、docker 一定启动；避免维护两套持久化测试、消除 aiosqlite 与 pg 方言差异掩盖问题的风险。

### 8. 迁移测试连真实 pg `s3mp` 库，downgrade base 可接受清空

`test_migrations.py` 当前用 aiosqlite 临时库做 `upgrade→downgrade base→upgrade` 往返。迁移到真实 pg：直接在 `s3mp` 库跑 `alembic upgrade head`（已 head，幂等）→ `downgrade base`（清空 30 表）→ `upgrade head`（重建）。测试环境可接受清空重建；不引入独立测试库。单 head 校验与表集合断言保留。

**备选**：独立 `s3mp_test` 库做迁移往返。**否决**——用户明确不用独立库、直接用、本身就是测试环境。

### 9. 真实端到端层验证基础设施连通性

新增 `tests/test_infrastructure_e2e.py`（或按 router 分文件）：
- pg 连通：`create_app(真实配置)` 起 app，经 HTTP 调一条只读端点（如 `GET /api/v1/users`），断言 200 且数据真实来自 pg。
- redis 连通：断言 `app.state.redis.ping()` 成功；readiness 端点 `/api/v1/health/ready` 返回 200 且 redis 检查通过。
- minio 连通：`MinioObjectStorageAdapter.readiness_probe()` 成功；经 HTTP 跑一个真实文件操作（如 initiate_upload→complete_upload→get_file→delete），断言对象真实在 minio 落地与删除。
- readiness 全栈：`/api/v1/health/ready` 在三个服务都健康时返回 200，断言响应含 database/redis/object_storage 检查。

### 10. 配置注入：`tests/_infrastructure.py` 普通模块暴露连接常量

因 `Settings(env_file=None)` 不自动加载 `.env`，新建 `tests/_infrastructure.py`（普通 Python 模块，**不是 conftest**，遵守项目无共享 conftest 约定）暴露：
- `TEST_DATABASE_URL`：默认 `postgresql+asyncpg://s3mp_app:bk-s3mp-backend@localhost:18110/s3mp`，env `S3MP_TEST_DATABASE_URL` 可覆盖。
- `TEST_REDIS_URL`：默认 `redis://:Bk-Skill@localhost:18113/0`，env 可覆盖。
- `TEST_S3_ENDPOINT/REGION/BUCKET/ACCESS_KEY/SECRET_KEY`：默认 `http://localhost:9000` / `us-east-1` / `s3mp-dev` / `s3mp-app` / `bk-s3mp-backend`，env 可覆盖。
- `real_settings()` 工厂：返回注入上述真实值的 `Settings`，供真实端到端与持久化测试用。
- `real_engine()` / `real_session()` 工厂：封装 `create_engine` + `AsyncSession`。

**备选**：用 `python-dotenv` 读 `deploy/.env`。**否决**——显式常量 + env 覆盖更可控、不引入 dotenv 运行时依赖、避免 `deploy/.env` 本身配置错误（端口/密码）污染测试。

### 11. 移除 aiosqlite 依赖

迁移 3 个现有 aiosqlite 测试到真实 pg 后，删 `pyproject.toml` 的 `aiosqlite` dev 依赖，`uv sync` 更新 lock。`src/s3mp/common/database.py` 的 sqlite PRAGMA 分支保留（生产不发 sqlite，但保留无副作用；不在本 change 改 src）。

## Risks / Trade-offs

- [fake 行为与真实 service 漂移] → fake 层只验证 HTTP 翻译与错误码契约；真实端到端层验证连通性与完整链路。两层互补，漂移由真实层暴露。
- [真实测试依赖 docker 服务可用] → docker 一定启动（用户保证）；若服务未起，测试直接失败（不 skip），暴露环境问题而非掩盖。
- [迁移往返 downgrade base 清空 `s3mp` 库] → 测试环境可接受；测试结束 upgrade head 重建。若库里有需保留的种子数据，迁移测试应排到最后跑或先备份。
- [持久化测试污染 `s3mp` 库] → 每测试事务回滚，不持久化；租户隔离测试用临时 UUID tenant，避免与既有数据冲突。
- [redis DB index 冲突] → 测试用 DB 0（与 app 一致），但仅做 ping/readiness，不写持久数据，无冲突。
- [HTTP 测试增多 + 真实 IO 导致运行时长增长] → 当前 83s / 176 用例；新增约 100+ 用例含真实 IO，预计增至 ~150-200s，单机可接受。按 router 用 `-k`/`--lf` 局部跑。
- [契约脚本单测需处理脚本硬编码 import] → 若 `check_openapi.py` 难以单测，降级为子进程跑脚本 + 临时 baseline 文件断言退出码。

## Migration Plan

1. 配置前置：修正 `deploy/secrets/database_url`（s3mp→s3mp_app 凭证）、`deploy/.env` redis（6379→18113 + 密码）；新建 `tests/_infrastructure.py`。
2. P0.1 `select_membership` 回归（1 文件，纯单元）。
3. P0.2 6 个 router fake HTTP 契约测试文件，逐 router 提交，每完成一个跑 `uv run pytest tests/test_<ctx>_http.py -q` 验证。
4. P0.3 租户隔离 HTTP 证据。
5. P1 横切语义 HTTP 测试（idempotency/etag/audit）。
6. P2 持久化测试（4 个 repository 文件，真实 pg + 事务回滚）。
7. P2.5 迁移 3 个现有 aiosqlite 测试到真实 pg，删 aiosqlite 依赖。
8. P3 真实端到端测试（pg/redis/minio 连通 + readiness + 真实文件操作）。
9. P4 契约脚本单测。
10. 全量门槛：`uv run ruff check .` / `uv run mypy` / `uv run python scripts/check_contracts.py` / `uv run python scripts/check_openapi.py` / `uv run pytest`（一条命令全跑，含真实集成）全绿。
11. 回滚策略：测试失败不影响生产代码；若某测试暴露真实 bug，先记录缺陷报告，再决定修 src 还是标记 xfail（优先修 src）。
