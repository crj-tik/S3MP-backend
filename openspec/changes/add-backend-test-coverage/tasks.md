## 0. 配置前置

- [x] 0.1 修正 `deploy/secrets/database_url` 为 `postgresql+asyncpg://s3mp_app:bk-s3mp-backend@host.docker.internal:18110/s3mp`（当前 `s3mp` 用户不存在，与 `alembic.ini` 一致）。验证：`cat deploy/secrets/database_url`
- [x] 0.2 修正 `deploy/.env` 的 `S3MP_REDIS_URL` 为 `redis://:Bk-Skill@localhost:18113/0`（当前端口 6379 错且缺密码）。验证：`grep S3MP_REDIS_URL deploy/.env`
- [x] 0.3 从 `pyproject.toml` 的 `[dependency-groups] dev` 移除 `aiosqlite`。验证：`uv sync && uv run python -c "import s3mp"`
- [x] 0.4 新建 `tests/_infrastructure.py`：暴露 `TEST_DATABASE_URL`（默认 `postgresql+asyncpg://s3mp_app:bk-s3mp-backend@host.docker.internal:18110/s3mp`）、`TEST_REDIS_URL`（默认 `redis://:Bk-Skill@localhost:18113/0`）、`TEST_S3_*`（默认 minio@9000/s3mp-dev/s3mp-app/bk-s3mp-backend）、`real_settings()`/`real_engine()`/`real_session()` 工厂，env 可覆盖。验证：`uv run python -c "from tests._infrastructure import TEST_DATABASE_URL; print(TEST_DATABASE_URL)"`

## 1. P0 回归与契约基线（fake HTTP 层）

- [x] 1.1 在 `tests/test_identity_security.py` 新增 `select_membership` 多 membership 回归：构造同一租户 `[Membership(suspended), Membership(active)]`，断言 `select_membership` 跳过 suspended 返回 active 的 PrincipalContext（对应 fix-bugs `break`→`continue` 修复点）。验证：`uv run pytest tests/test_identity_security.py -k tenant_selection -q`
- [x] 1.2 新建 `tests/test_identity_http.py`：覆盖 `get_me`/`list_users`/`get_user`/`list_members`/`create_member`/`get_member`/`update_member`/`list_groups`/`create_group`/`list_group_members` 等 operationId 的成功路径 + 一条 401（无 context）。fake 注入 `app.state.identity_management` 与 `identity_context_provider`。验证：`uv run pytest tests/test_identity_http.py -q`
- [x] 1.3 新建 `tests/test_authorization_http.py`：覆盖 `get_effective_permissions`/`simulate_authorization`/`list_role_bindings`/`create_role_binding`/`revoke_role_binding` 成功路径 + 跨租户 principal 查询返回 `404 resource_not_found` 不泄露。验证：`uv run pytest tests/test_authorization_http.py -q`
- [x] 1.4 新建 `tests/test_applications_http.py`：覆盖 `list_applications`/`create_application`/`get_application`/`list_api_keys` 成功路径，以及 API Key 一次性 secret——issue 返回 raw secret，再次查询返回 `410 secret_not_retrievable`。验证：`uv run pytest tests/test_applications_http.py -q`
- [x] 1.5 新建 `tests/test_files_http.py`：覆盖 `list_files`/`get_file`/`initiate_upload`/`complete_upload`/`list_multipart`/`abort_multipart`/`copy_object`/`move_object`/`delete_object` 成功路径 + 一条 401。验证：`uv run pytest tests/test_files_http.py -q`
- [x] 1.6 新建 `tests/test_governance_http.py`：覆盖 `get_quota`/`update_quota`/`list_audit_events` 成功路径 + 一条失败路径。验证：`uv run pytest tests/test_governance_http.py -q`
- [x] 1.7 新建 `tests/test_storage_http.py`：覆盖 `list_storage_connections`/`create_storage_connection`/`get_storage_connection` 成功路径 + 缺失配置返回不可用。验证：`uv run pytest tests/test_storage_http.py -q`
- [x] 1.8 租户隔离 HTTP 证据：在 identity/authorization/files 的 HTTP 测试中，注入属于 tenant B 的 PrincipalContext 请求 tenant A 的资源 ID，断言 `404 resource_not_found` 且响应体不含 A 的任何字段。验证：`uv run pytest tests/test_identity_http.py tests/test_authorization_http.py tests/test_files_http.py -k cross_tenant -q`

## 2. P1 横切语义 HTTP 验证（fake）

- [x] 2.1 新建 `tests/test_idempotency_http.py`：对一条 mutating 端点（如 `create_application`），首次带 Idempotency-Key 成功，第二次同 key 不同 body 返回 `409 idempotency_key_reused` 且 fake service 只被调用一次。验证：`uv run pytest tests/test_idempotency_http.py -q`
- [x] 2.2 在 `tests/test_files_http.py` 或独立文件加 ETag/If-Match：成功响应带 ETag；带过期 `If-Match` 的更新请求返回冲突错误码。验证：`uv run pytest tests/test_files_http.py -k etag -q`
- [x] 2.3 新建 `tests/test_audit_failure_http.py`：fake audit store 抛持久化异常，高风险 mutation（copy/move/delete/签发预签名）返回 `503 audit_unavailable`，且 fake object storage 断言未被调用（fail-close）。验证：`uv run pytest tests/test_audit_failure_http.py -q`

## 3. P2 持久化层测试（真实 postgresql，事务回滚隔离）

- [x] 3.1 新建 `tests/test_files_repository.py`：真实 pg `s3mp` 库，每测试事务回滚，验证 `SqlAlchemyFileStore` 的 tenant-scoped 查询（跨租户返回 None）、file 记录 CRUD 往返、upload session 状态流转。验证：`uv run pytest tests/test_files_repository.py -q`
- [x] 3.2 新建 `tests/test_applications_repository.py`：验证 `SqlAlchemyApplicationStore` 的 tenant-scoped 查询、application/Api Key CRUD、secret verifier 持久化（不存 raw secret）。验证：`uv run pytest tests/test_applications_repository.py -q`
- [x] 3.3 新建 `tests/test_storage_repository.py`：验证 `SqlAlchemyStorageStore` 的 tenant-scoped 查询、storage connection CRUD、配置缺失标记不可用。验证：`uv run pytest tests/test_storage_repository.py -q`
- [x] 3.4 新建 `tests/test_governance_repository.py`：验证 `SqlAlchemyQuotaStore`/`SqlAlchemyAuditStore` 的 tenant-scoped 查询、配额预留与结算、audit 事件写入与脱敏字段。验证：`uv run pytest tests/test_governance_repository.py -q`

## 4. P2.5 迁移现有 aiosqlite 测试到真实 postgresql

- [x] 4.1 迁移 `tests/test_identity_repository.py` 到真实 pg：engine fixture 改用 `real_engine()` 连 `s3mp` 库；删 `test_application_engine_enables_sqlite_foreign_keys`（sqlite PRAGMA 专属），保留 `test_composite_foreign_keys_reject_cross_tenant_links`（pg FK 已验证）；每测试事务回滚。验证：`uv run pytest tests/test_identity_repository.py -q`
- [x] 4.2 迁移 `tests/test_identity_constraints.py` 到真实 pg：aiosqlite 临时库改 `s3mp` 库 + 事务回滚。验证：`uv run pytest tests/test_identity_constraints.py -q`
- [x] 4.3 迁移 `tests/test_migrations.py` 到真实 pg `s3mp` 库：`migration_config` 默认用 `alembic.ini` 的 `s3mp_app@18110/s3mp`；`upgrade head`→`downgrade base`→`upgrade head` 在 `s3mp` 库跑（清空重建，测试环境可接受）。验证：`uv run pytest tests/test_migrations.py -q`

## 5. P3 真实服务端到端测试

- [x] 5.1 新建 `tests/test_identity_e2e.py`：`create_app(real_settings())` 注入真实 identity service + store，经 AsyncClient 打 `create_member`→`get_member`→`update_member` 完整链路，验证真实落 pg。验证：`uv run pytest tests/test_identity_e2e.py -q`
- [x] 5.2 新建 `tests/test_files_e2e.py`：真实 file service + `MinioObjectStorageAdapter`，打 `initiate_upload`→`complete_upload`→`get_file`→`copy_object`→`move_object`→`delete_object` 完整链路，验证真实落 minio + pg。验证：`uv run pytest tests/test_files_e2e.py -q`
- [x] 5.3 新建 `tests/test_readiness_e2e.py`：`/api/v1/health/ready` 连真实 pg/redis/minio，断言 200 且响应含 database/redis/object_storage 检查通过。验证：`uv run pytest tests/test_readiness_e2e.py -q`
- [x] 5.4 新建 `tests/test_infrastructure_e2e.py`：直接验证 `create_redis(TEST_REDIS_URL)` 连接 + ping 成功；`MinioObjectStorageAdapter(real_settings()).readiness_probe()` 成功；`create_engine(TEST_DATABASE_URL)` + `SELECT 1` 成功。验证：`uv run pytest tests/test_infrastructure_e2e.py -q`

## 6. P4 契约脚本单测

- [x] 6.1 新建 `tests/test_contract_checks.py`：直接调用 `scripts/check_openapi.py` 的 `operation_signatures`/`main`，构造基线多出端点的临时 OpenAPI 文件，断言 `main()` 返回非 0；并验证正常基线返回 0。验证：`uv run pytest tests/test_contract_checks.py -q`

## 7. 全量门槛验证

- [x] 7.1 全量门槛：`uv run ruff check .`（0 error）、`uv run mypy`（0 error）、`uv run python scripts/check_contracts.py`（通过）、`uv run python scripts/check_openapi.py`（通过）、`uv run pytest`（一条命令全跑，含真实集成，≥176 + 新增全绿，无 flaky，docker 必须运行）。失败给出根因分析，不掩盖。
