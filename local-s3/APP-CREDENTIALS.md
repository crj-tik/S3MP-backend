# S3MP 应用账号

`MINIO_ROOT_USER` 和 `MINIO_ROOT_PASSWORD` 是 MinIO 管理员账号，只供初始化容器和控制台管理使用，不要写入后端的 S3 连接配置。

启动 Compose 后，初始化容器会自动创建一个权限受限的 S3MP 应用账号：

```text
access key: s3mp-app
secret key: change-me-s3mp-local
```

实际值由 `.env` 中的 `S3MP_ACCESS_KEY` 和 `S3MP_SECRET_KEY` 决定。

该应用账号只允许访问 `S3MP_LOCAL_BUCKET`，默认权限包括：

- 查询 bucket 和 bucket location；
- 读取对象；
- 写入对象；
- 删除对象；
- multipart 上传相关操作。

后端应配置应用账号：

```text
endpoint=http://localhost:9000
region=us-east-1
path_style=true
bucket=s3mp-dev
access_key=s3mp-app
secret_key=change-me-s3mp-local
```

如果修改了 `.env` 中的应用密码，需要重新执行初始化容器：

```powershell
docker compose up -d --force-recreate minio-init
```
