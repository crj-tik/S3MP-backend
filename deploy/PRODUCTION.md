# Linux Docker 生产部署

本部署方式构建一个 `s3mp` 应用镜像：其中包含前端构建产物、Nginx 和 Python/uv 后端
运行时。迁移、初始化、API、worker 与 scheduler 复用这个相同镜像；Linux
宿主机只需 Docker Engine、Docker Compose plugin、Git、`curl` 与 `openssl`；不需要
安装 nvm、Node、npm、Python 或 uv。

## 1. 宿主机准备

以 Ubuntu/Debian 为例，安装 Docker Engine 和 Compose plugin 后启用 Docker：

```bash
sudo systemctl enable --now docker
docker version
docker compose version
```

建议至少预留 4 vCPU、8 GiB RAM、80 GiB SSD。生产服务器必须通过防火墙或安全组
仅开放 HTTPS 入口；Compose 默认将前端 HTTP 绑定到 `8080`，PostgreSQL 与 Redis
均不对宿主机发布端口。文件对象使用预先配置的线上 S3 服务。

## 2. 配置环境与密钥

将全部配置和密钥放在仓库外的一个文件中：

```bash
sudo install -m 600 deploy/.env.production.example /opt/s3mp/s3mp.env
sudoedit /opt/s3mp/s3mp.env
sudo chmod 600 /opt/s3mp/s3mp.env
openssl rand -base64 48  # 将输出填入 S3MP_API_KEY_PEPPER
```

在 `/opt/s3mp/s3mp.env` 中填入线上 S3 的 endpoint、region、path-style 配置、已创建的
Bucket 名称及其容量，以及 PostgreSQL、Redis、S3、API key pepper 和首个管理员的密码。
`S3MP_POSTGRES_PASSWORD` 与 `S3MP_REDIS_PASSWORD` 写原始密码；连接 URL 中同一个密码必须
URL 编码。不要将该文件提交到 Git、复制到截图或放入镜像构建上下文。

## 3. 首次部署

在后端仓库根目录执行。若在服务器上构建，使用第一组命令；若在本机或 CI 构建并将唯一
应用镜像上传到服务器，使用第二组命令。PostgreSQL 和 Redis 镜像仍会由 Compose 单独拉取，
它们不是业务应用镜像的一部分。

```bash
# 服务器构建
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml build
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml up -d
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml ps
curl -fsS http://127.0.0.1:8080/health/ready
```

```bash
# 本机或 CI 构建一个应用镜像，然后传输至服务器（不含任何数据库数据）
docker buildx build --load \
  --build-context frontend=../S3MP-frontend \
  -f deploy/Dockerfile.production \
  -t s3mp:20260824 .
docker save -o s3mp-20260824.tar s3mp:20260824

# 服务器：上传 tar 后导入，并在 /opt/s3mp/s3mp.env 中设置
# S3MP_APP_IMAGE=s3mp:20260824
docker load -i s3mp-20260824.tar
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml up -d
```

`api` 是唯一对外发布 HTTP 端口的应用容器：镜像内的 Nginx 提供前端静态资源，并把
`/api/` 转给同一容器中的后端进程。`migrate` 是一次性服务：它成功完成后，`bootstrap` 会对齐基础平台角色，并在首次部署时
创建配置的平台管理员；随后 API、worker 和 scheduler 才会启动。该流程只初始化架构和
基础数据，不导入测试或业务数据。线上 S3 的 Bucket 与最小权限应用凭据须在部署前由存储
服务管理员创建好。

部署后，在公网入口前配置 HTTPS 终止，例如由已有的 Nginx、Caddy 或负载均衡器把
`https://s3mp.example.com` 转发到 `127.0.0.1:8080`。前端通过同源的 `/api/` 调用 API，
因此不要把 API 单独暴露到公网。

## 4. 日常操作

```bash
# 查看服务状态与日志
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml ps
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml logs -f api worker file-retention-scheduler

运行日志默认每行一个 JSON 对象，包含 `request_id` 或后台 `operation_id`。审计记录和 API 使用量投影仍保存在原有数据库表中；运行日志只输出到容器标准输出。可用 `S3MP_LOG_SLOW_OPERATION_MS` 调整 MinIO、Redis 与 Repository 的慢操作告警阈值，本地排查时可将 `S3MP_LOG_FORMAT=text` 改为文本格式。

# 升级：先拉取指定版本，再重建并启动；迁移由 migrate 服务自动执行
git checkout <release-tag>
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml up -d --build

# 只停止服务，保留数据卷
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml down
```

禁止使用 `down -v` 作为常规停止或回滚命令；它会删除 PostgreSQL 和 Redis 数据卷。

## 4.1 文件软删除保留调度

`file-retention-scheduler` 每天北京时间凌晨处理到期文件。Redis 的 `s3mp:file-retention:due` ZSET 仅是调度索引；Compose 使用持久化 `redis-data` 卷，并启用 AOF（`appendfsync everysec`）。PostgreSQL 保留软删除状态、到期时间和调度 Outbox，因此 Redis 重启或短暂丢失写入后会自动补回索引。

## 概览统计与第三方 API 调用观测

同一应用镜像还运行 `dashboard-summary-scheduler` 和 `api-observability-worker`：前者每小时生成一次租户文件空间快照，后者消费 Redis Stream `s3mp:api-usage:events` 并写入 PostgreSQL 聚合指标。Redis 使用命名卷和 AOF 持久化；它只是异步缓冲，数据库才是指标与异常请求引用的最终存储。

异常请求引用默认保留 90 天，可通过 `S3MP_API_OBSERVABILITY_ERROR_RETENTION_DAYS` 调整。不要记录或导出该 Stream 的请求内容、文件路径、凭据或异常堆栈。

```bash
# 查看观测 worker 的处理/积压诊断
sudo docker compose --env-file deploy/.env -f deploy/compose.production.yaml logs --tail=200 api-observability-worker
sudo docker compose --env-file deploy/.env -f deploy/compose.production.yaml exec redis \
  sh -c 'redis-cli -a "$S3MP_REDIS_PASSWORD" XLEN s3mp:api-usage:events'

# 查看最近一次文件空间快照是否已生成
sudo docker compose --env-file deploy/.env -f deploy/compose.production.yaml exec postgres \
  psql -U s3mp -d s3mp -c 'SELECT tenant_id, generated_at FROM tenant_storage_summary ORDER BY generated_at DESC LIMIT 20;'
```

排障时查看 `file-retention-scheduler` 日志中的 `dispatched`、`reconciled`、`purged` 指标。不要手动清空该 ZSET；即使误清空，系统会补偿，但会增加恢复时间。

## 5. 备份与回滚

定期将以下数据备份到服务器外的受控存储：

```bash
# PostgreSQL 逻辑备份
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml \
  exec -T postgres pg_dump -U s3mp -Fc s3mp > /secure-backup/s3mp-$(date +%F).dump

# 对象文件：由线上 S3 服务按其备份与版本策略保护；不要仅备份数据库。
```

应用回滚时切换到上一稳定 Git tag 后重新执行 `up -d --build`，保留全部数据卷。仅当
迁移已经确认可回退且不会丢失业务数据时，才通过 `migrate` 容器执行 Alembic downgrade。
