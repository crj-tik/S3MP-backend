# 本地容器联调

默认 `compose.yaml` 启动 PostgreSQL、Redis、一次性数据库迁移、S3MP API、worker 和
platform-scheduler。PostgreSQL 和 Redis 仅在 Compose 内网暴露，并分别使用命名卷
`postgres-data` 与 `redis-data` 持久化；不会占用宿主机的 `5432` 或 `6379` 端口。
MinIO/S3 仍由外部服务提供，Compose 不会创建或管理 Bucket。

## 前置条件

- MinIO 已在主机 `9000` 端口运行，目标 bucket 已存在，且应用凭据有读写权限。

从 `deploy/.env.example` 创建本地、未跟踪的 `deploy/.env`，填入 PostgreSQL/Redis
密码、MinIO 应用凭据和至少 32 字节的 `S3MP_API_KEY_PEPPER`。不要将该文件提交到 Git。
密码会同时作为服务密码和连接 URL 的一部分，使用字母、数字、`.`、`_`、`-` 等 URL-safe
字符；不要在此处写 URL 编码后的值。

## 初始化与启动

```powershell
docker compose -f deploy/compose.yaml up -d --build
docker compose -f deploy/compose.yaml ps
Invoke-WebRequest http://localhost:19101/health/ready | Select-Object -Expand Content
```

首次启动时 PostgreSQL 会初始化 `s3mp` 数据库与 `s3mp` 用户；`migrate` 服务会创建或
升级表、字段、索引和权限基线。后续启动会复用已有卷，不会清除数据。Redis 使用
`requirepass` 与 AOF 持久化，Redis 不需要 schema 初始化。MinIO bucket 不由该 Compose
自动创建，以避免误操作现有对象存储；就绪检查会验证 bucket 与应用凭据。

`bootstrap` 服务在 `migrate` 成功后执行。它始终对齐内置平台角色；只有
`S3MP_BOOTSTRAP_ADMIN_ENABLED=true` 时，才会在不存在活动平台管理员时创建配置的首个
管理员。该流程不会插入测试数据，也不会覆盖已有管理员。

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
