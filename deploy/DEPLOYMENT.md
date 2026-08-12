# S3MP 后端部署与运维手册

## 1. 契约版本

| 文件 | 版本 | 说明 |
|------|------|------|
| `contracts/openapi.yaml` | 1.0.0 | 规范 REST API 契约，覆盖 Context/Users/Members/Groups/Roles/Authorization/Applications/API Keys/Storage/Files/Uploads/Multipart/Quotas/Audit |
| `contracts/api-conventions.md` | 1.0.0 | 通用约定：认证、分页、幂等、错误码、时间格式、文件语义 |
| `contracts/error-codes.yaml` | 1.0.0 | 稳定机器错误码目录 |
| `contracts/permission-catalog.yaml` | 1.0.0 | 权限操作目录 |
| `contracts/examples/` | 1.0.0 | 成功/空状态/拒绝/冲突/过期/部分失败 契约示例 |

**契约兼容性级别**: 1.0.0（向后兼容）。新增可选字段和端点不视为 breaking change。

---

## 2. 前端同步说明

### 2.1 契约消费方式

前端项目应将 `contracts/` 目录作为只读依赖：

```bash
# 方式一：git submodule（推荐）
git submodule add <backend-repo-url> contracts/s3mp-backend
cd contracts/s3mp-backend
git checkout <contract-version-tag>

# 方式二：脚本拉取
./scripts/sync-contracts.sh --repo <backend-repo-url> --ref v1.0.0
```

### 2.2 代码生成

```bash
# OpenAPI → TypeScript types + API client
npx openapi-typescript contracts/s3mp-backend/contracts/openapi.yaml \
  -o src/generated/api-types.ts

# 错误码 → TypeScript enum
node scripts/generate-error-codes.mjs \
  contracts/s3mp-backend/contracts/error-codes.yaml \
  -o src/generated/error-codes.ts

# 权限目录 → TypeScript enum
node scripts/generate-permissions.mjs \
  contracts/s3mp-backend/contracts/permission-catalog.yaml \
  -o src/generated/permissions.ts
```

### 2.3 契约变更通知

后端变更契约后应：
1. 更新 `contracts/` 文件并打 tag（如 `v1.1.0`）
2. 输出变更摘要，标注兼容性影响（breaking/additive/fix）
3. 前端执行 `git submodule update --remote` 后重新生成类型并验证编译

### 2.4 Mock 服务

前端可使用 `contracts/examples/` 中的示例响应搭建本地 Mock：

```bash
npx prism mock contracts/s3mp-backend/contracts/openapi.yaml --port 4010
```

---

## 3. 部署手册

### 3.1 环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.12+ | 运行时 |
| PostgreSQL | 17 | 主数据库 |
| Redis | 7 | 限流、缓存、任务协调 |
| Docker | 24+ | 容器化部署 |

### 3.2 本地开发部署

```bash
# 1. 安装依赖
uv sync

# 2. 准备密钥（生产环境使用文件挂载）
cp deploy/.env.example deploy/.env
mkdir -p deploy/secrets
echo "postgres://s3mp:s3mp@localhost:5432/s3mp" > deploy/secrets/database_url
echo "s3mp-dev-password" > deploy/secrets/postgres_password

# 3. 启动基础设施
docker compose -f deploy/compose.yaml up -d postgres redis

# 4. 运行数据库迁移
uv run alembic upgrade head

# 5. 启动 API
uv run uvicorn s3mp.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3.3 生产部署

```bash
# 1. 构建镜像
docker build -f deploy/Dockerfile -t s3mp-api:latest .

# 2. 准备生产密钥文件（不可提交到仓库）
#   deploy/secrets/database_url       → postgresql://user:pass@host:5432/s3mp
#   deploy/secrets/postgres_password  → <strong-password>
#   deploy/secrets/redis_url          → redis://user:pass@host:6379/0

# 3. 设置环境变量
#   S3MP_ENVIRONMENT=production
#   S3MP_LOG_LEVEL=WARNING
#   S3MP_DATABASE_URL_FILE=/run/secrets/database_url
#   S3MP_REDIS_URL_FILE=/run/secrets/redis_url

# 4. 启动服务栈
docker compose -f deploy/compose.yaml up -d

# 5. 运行迁移
docker compose -f deploy/compose.yaml exec api uv run alembic upgrade head

# 6. 验证健康检查
curl http://localhost:8000/api/v1/health
```

### 3.4 健康检查端点

| 端点 | 用途 | 预期响应 |
|------|------|----------|
| `GET /api/v1/health` | 存活性检查 | 200 `{"status":"ok"}` |
| `GET /api/v1/health/ready` | 就绪性检查（含 DB/Redis） | 200 或 503 |

### 3.5 安全配置清单

- [ ] 生产环境强制使用 `S3MP_*_FILE` 秘密文件引用，禁止环境变量直接传递密钥
- [ ] PostgreSQL 使用 TLS 连接
- [ ] Redis 配置 `requirepass`
- [ ] 会话 Cookie 设置 `Secure; HttpOnly; SameSite=Lax`
- [ ] API 部署在反向代理后（nginx/Caddy），启用 HTTPS
- [ ] `S3MP_ENVIRONMENT=production` 启用生产安全策略
- [ ] 审计日志写入独立持久化存储，不可经业务 API 修改

---

## 4. 回滚手册

### 4.1 回滚策略

回滚原则：按 capability flag 禁用新能力；数据库迁移采用向前兼容扩展，避免自动删除对象和审计数据。

### 4.2 紧急回滚步骤

```bash
# 1. 切回上一个稳定版本
docker compose -f deploy/compose.yaml down
git checkout <previous-stable-tag>
docker build -f deploy/Dockerfile -t s3mp-api:rollback .
docker compose -f deploy/compose.yaml up -d

# 2. 如果迁移已执行，评估是否需要 downgrade：
#    查看当前迁移版本
docker compose -f deploy/compose.yaml exec api uv run alembic current
#    仅当迁移是纯扩展（新增表/列）且无业务影响时可保留；
#    否则执行 downgrade 到目标版本
docker compose -f deploy/compose.yaml exec api uv run alembic downgrade <target-revision>

# 3. 验证健康检查
curl http://localhost:8000/api/v1/health/ready
```

### 4.3 能力开关（Capability Flag）降级

| Flag | 影响 | 降级方式 |
|------|------|----------|
| `storage_connection.capability_flags` | S3 操作允许列表 | 数据库设置 `multipart=false`, `delete_object=false` 等 |
| `quota.limit_bytes` | 存储配额 | 设置为 0 阻止新上传 |
| API Key `status` | 应用访问 | 批量 `revoke` 受影响 Key |
| `membership.status` | 用户权限 | 设置为 `suspended` 即时回收 |

### 4.4 数据恢复

- 审计数据（`audit_event`）仅追加，回滚不删除
- 文件对象（`file_object`）状态变更可逆：`pending` → 清理，`available` → 保留
- 配额预留（`quota_reservation`）过期后自动释放
- Multipart 会话（`multipart_session`）过期后由 Worker 自动清理

### 4.5 回滚验证清单

- [ ] 健康检查 `/api/v1/health/ready` 返回 200
- [ ] `/api/v1/me` 认证正常
- [ ] 文件列表/读取功能正常
- [ ] 已有预签名 URL 在有效期内仍可用
- [ ] 审计日志完整无丢失
- [ ] 迁移版本与代码版本一致

---

## 5. 数据库迁移

### 5.1 迁移历史

| 版本 | 内容 |
|------|------|
| 0001_initial | 初始基线 |
| 0002_identity | 租户与身份持久化 |
| 0003_authorization | 用户组、角色、权限、RoleBinding |
| 0004_application_access | 应用、Owner、API Key |
| 0005_storage_files | 存储连接与文件持久化 |
| 0006_multipart_governance | Multipart、对象操作、配额、审计 |
| 0007_access_review | 访问审查、审批请求 |

### 5.2 迁移操作

```bash
# 生成新迁移
uv run alembic revision --autogenerate -m "description"

# 升级到最新
uv run alembic upgrade head

# 回退一个版本
uv run alembic downgrade -1

# 查看迁移 SQL（不执行）
uv run alembic upgrade head --sql
```

---

## 6. 监控与告警

### 6.1 关键指标

| 指标 | 告警阈值 | 说明 |
|------|----------|------|
| API 响应时间 P95 | > 500ms | 性能退化 |
| 登录失败率 | > 10/min | 暴力破解嫌疑 |
| 审计写入失败 | > 0 | 高风险操作 fail-close |
| 配额超额 | > 0 | 存储隔离 |
| 孤儿应用 | > 0 | Owner 接管流程 |

### 6.2 安全告警类别

| 类别 | 严重级别 | 触发条件 |
|------|----------|----------|
| `auth_failure` | WARNING | 连续登录失败 |
| `privilege_escalation` | CRITICAL | 越权委派尝试 |
| `rate_limit` | WARNING | 限流触发 |
| `audit_failure` | CRITICAL | 审计写入失败 |
| `orphan_detected` | CRITICAL | 检测到孤儿应用 |
| `delegation_violation` | CRITICAL | 委派越界 |
---

## 7. 本地基础设施

### 7.1 依赖组件

| 组件 | 默认端口 | 用途 |
|------|----------|------|
| PostgreSQL | `platform-infra-postgres-1:18110` | 主数据库 |
| Redis | `platform-infra-redis-1:18113` | 限流、缓存、幂等、worker 协调 |
| MinIO | `localhost:9000` (独立) | S3 兼容对象存储 |

### 7.2 启动顺序

```bash
# 1. 确保 PostgreSQL 和 Redis 已运行
docker ps --filter "name=platform-infra"

# 2. 启动独立 MinIO（如需要文件功能）
docker compose -f local-s3/compose.yaml up -d

# 3. 运行数据库迁移
uv run alembic upgrade head

# 4. 启动 API
uv run uvicorn s3mp.main:app --host 0.0.0.0 --port 8000

# 5. 验证就绪
curl http://localhost:8000/health/ready
# → {"status":"ok","checks":{"database":"ok","redis":"ok","object_storage":"ok"}}
```

### 7.3 S3 开发配置

通过 `.env` 文件设置（不嵌入源码）：

```ini
S3MP_S3_ENDPOINT=http://localhost:9000
S3MP_S3_REGION=us-east-1
S3MP_S3_BUCKET=s3mp-dev
S3MP_S3_ACCESS_KEY=<minio-access-key>
S3MP_S3_SECRET_KEY=<minio-secret-key>
S3MP_S3_PATH_STYLE=true
```

生产环境强制使用 `S3MP_S3_ACCESS_KEY_FILE` 和 `S3MP_S3_SECRET_KEY_FILE` 文件引用。
