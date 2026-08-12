# 本地 S3（MinIO）

这个目录是独立的本地 S3 模拟环境，不属于后端生产部署 Compose。后端程序只需要把它当作一个普通的 S3-compatible endpoint 使用。

## 启动

首次使用时，如果需要修改账号、密码或端口：

```powershell
Copy-Item .env.example .env
```

然后在本目录执行：

```powershell
docker compose up -d
```

查看状态：

```powershell
docker compose ps
docker compose logs minio
```

## 访问地址

- S3 API：`http://localhost:9000`
- MinIO 控制台：`http://localhost:9001`
- 默认账号：`minioadmin`
- 默认密码：`minioadmin`
- 默认 bucket：`s3mp-dev`

如果创建了 `.env`，以 `.env` 中的账号、密码和端口为准。

## 后端连接参数

后端直接在宿主机运行时：

```text
endpoint=http://localhost:9000
region=us-east-1
path_style=true
bucket=s3mp-dev
```

后端也在同一个 Compose 网络中运行时，endpoint 应改为：

```text
http://minio:9000
```

本地 MinIO 默认使用 HTTP；后端开发配置需要允许非 TLS endpoint。生产环境仍应保持 HTTPS，不要复用这里的账号或配置。

## 停止

停止容器但保留对象数据：

```powershell
docker compose down
```

查看 bucket 和对象可以直接打开控制台。`minio-data` 是独立 Docker volume，删除它会清空本地 S3 数据。
