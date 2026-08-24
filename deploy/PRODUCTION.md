# Linux Docker 生产部署

本部署方式在容器中运行前端构建、Python/uv 后端运行时和所有基础服务。Linux
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

将配置和密钥放在仓库外：

```bash
sudo install -d -m 700 /opt/s3mp/secrets
sudo install -m 600 deploy/.env.production.example /opt/s3mp/s3mp.env
sudoedit /opt/s3mp/s3mp.env
sudoedit /opt/s3mp/secrets/postgres_password
sudoedit /opt/s3mp/secrets/redis_password
sudoedit /opt/s3mp/secrets/database_url
sudoedit /opt/s3mp/secrets/redis_url
sudoedit /opt/s3mp/secrets/s3_access_key
sudoedit /opt/s3mp/secrets/s3_secret_key
sudo sh -c 'openssl rand -base64 48 > /opt/s3mp/secrets/api_key_pepper'
sudo chmod 600 /opt/s3mp/secrets/* /opt/s3mp/s3mp.env
```

在 `/opt/s3mp/s3mp.env` 中填入线上 S3 的 endpoint、region、path-style 配置、已创建的
Bucket 名称及其容量；各密钥文件的内容说明见 [secrets.example/README.md](secrets.example/README.md)。
生产 API 拒绝将数据库、Redis、S3 与 API Key pepper 直接写为环境变量，必须使用这些文件引用。

## 3. 首次部署

在后端仓库根目录执行：

```bash
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml build
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml up -d
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml ps
curl -fsS http://127.0.0.1:8080/api/v1/health/ready
```

`migrate` 是一次性服务：它成功完成后 API、worker 和 scheduler 才会启动。线上 S3 的
Bucket 与最小权限应用凭据须在部署前由存储服务管理员创建好。

部署后，在公网入口前配置 HTTPS 终止，例如由已有的 Nginx、Caddy 或负载均衡器把
`https://s3mp.example.com` 转发到 `127.0.0.1:8080`。前端通过同源的 `/api/` 调用 API，
因此不要把 API 单独暴露到公网。

## 4. 日常操作

```bash
# 查看服务状态与日志
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml ps
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml logs -f api worker

# 升级：先拉取指定版本，再重建并启动；迁移由 migrate 服务自动执行
git checkout <release-tag>
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml up -d --build

# 只停止服务，保留数据卷
docker compose --env-file /opt/s3mp/s3mp.env -f deploy/compose.production.yaml down
```

禁止使用 `down -v` 作为常规停止或回滚命令；它会删除 PostgreSQL 和 Redis 数据卷。

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
