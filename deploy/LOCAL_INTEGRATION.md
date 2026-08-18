# 本地容器联调

默认 `compose.yaml` 启动 S3MP 的 API、worker 和 platform-scheduler，复用已在 Windows 主机
运行的 PostgreSQL、Redis 和 MinIO，不会创建新的数据库、Redis 卷或 MinIO
实例。Docker Desktop 容器通过 `host.docker.internal` 访问宿主机上的现有服务。

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
docker compose -f deploy/compose.yaml up -d api worker platform-scheduler
docker compose -f deploy/compose.yaml ps
Invoke-WebRequest http://localhost:19101/health/ready | Select-Object -Expand Content
```

迁移会创建或升级 PostgreSQL 的表、字段、索引和权限基线；不会清除既有数据。
Redis 不需要 schema 初始化。MinIO bucket 不由该 Compose 自动创建，以避免误
操作现有对象存储；就绪检查会验证 bucket 与应用凭据。

## 共享 S3 Profile

S3MP 只使用一个平台级共享 Bucket。租户和应用不会提交 Endpoint、Region、
Bucket、凭据或物理对象前缀：新建逻辑存储空间时只绑定应用，服务端为该租户
创建受管的兼容关联记录，并从应用不可变命名空间派生对象 Key。

`S3MP_S3_ENDPOINT`、`S3MP_S3_REGION`、`S3MP_S3_PATH_STYLE`、
`S3MP_S3_BUCKET` 与 S3 凭据均须在 `deploy/.env` 中成组配置。MinIO 本地联调
使用 `http://host.docker.internal:9000` 和 `path_style=true`；生产 S3 若其网络
或网关要求 path-style，同样设为 `true`。启动时会以配置的 Region 和寻址方式
执行只读 `HeadBucket` 就绪检查，不会创建或删除生产对象。

生产切换前，应使用生产部署凭据执行一次 `/health/ready`，并保存该次结果；
该检查通过才允许接收文件写入。切换后使用
`python scripts/audit_shared_s3_namespace.py` 观察隔离记录、重复命名空间和旧
目标引用。脚本没有待处理项时，才可确认当前环境完成旧记录收敛。

首个平台管理员须在迁移后通过受控脚本单独创建。支持访问到期回收须由外部调度
`platform-scheduler` 会每 60 秒执行一次支持访问过期回收；发生临时故障时会记录结构化日志并在下一轮重试。仍可使用 `python scripts/expire_support_access.py` 手工执行一次回收。

## 自管基础设施模式

未来需要独立 PostgreSQL 与 Redis 时，使用：

```powershell
docker compose -f deploy/compose.managed-infra.yaml up -d --build
```

该模式会创建独立的 Compose 卷，仍不会启动或初始化 MinIO。
