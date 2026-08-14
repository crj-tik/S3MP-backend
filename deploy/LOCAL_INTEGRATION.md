# 本地容器联调

默认 `compose.yaml` 仅启动 S3MP 的 API 和 worker，复用已在 Windows 主机
运行的 PostgreSQL、Redis 和 MinIO，不会创建新的数据库、Redis 卷或 MinIO
实例。Docker Desktop 容器通过 `host.docker.internal` 访问这些现有服务。

## 前置条件

- PostgreSQL 已在主机 `18110` 端口运行。
- Redis 已在主机 `18113` 端口运行。
- MinIO 已在主机 `9000` 端口运行，目标 bucket 已存在，且应用凭据有读写权限。

从 `deploy/.env.example` 创建本地、未跟踪的 `deploy/.env`，填入现有服务的
连接信息、MinIO 应用凭据和至少 32 字节的 `S3MP_API_KEY_PEPPER`。不要将该文件
提交到 Git。

## 初始化与启动

```powershell
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml run --rm api python -m alembic upgrade head
docker compose -f deploy/compose.yaml up -d api worker
docker compose -f deploy/compose.yaml ps
Invoke-WebRequest http://localhost:19101/health/ready | Select-Object -Expand Content
```

迁移会创建或升级 PostgreSQL 的表、字段、索引和权限基线；不会清除既有数据。
Redis 不需要 schema 初始化。MinIO bucket 不由该 Compose 自动创建，以避免误
操作现有对象存储；就绪检查会验证 bucket 与应用凭据。

首个平台管理员须在迁移后通过受控脚本单独创建。支持访问到期回收须由外部调度
至少每分钟运行 `python scripts/expire_support_access.py`。

## 自管基础设施模式

未来需要独立 PostgreSQL 与 Redis 时，使用：

```powershell
docker compose -f deploy/compose.managed-infra.yaml up -d --build
```

该模式会创建独立的 Compose 卷，仍不会启动或初始化 MinIO。
