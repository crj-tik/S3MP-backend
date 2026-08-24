# 应用 API Key 文件对接指南

本文面向第三方应用，说明如何通过 S3MP 应用 API Key 查看文件、上传文件和下载文件。

## 1. 基本约定

### 服务地址

示例服务地址为 `http://localhost:19101`。生产环境请替换为平台分配的 API 地址。

### 认证与审计

所有请求均携带以下请求头：

```http
Authorization: S3MP-Key <API_KEY>
```

所有应用数据面接口还必须携带查询参数 `application_code`：

```text
?application_code=postUser
```

- API Key 决定**目标应用**和它可访问的目录范围。
- `application_code` 仅表示**操作方应用**，用于审计；它必须是与目标应用同租户且有效的应用代码。
- 不传 `application_id`，也不传 bucket、租户 ID、物理对象路径。

如果 Key 在创建时绑定了“存取目录”，以下接口中的上传对象路径和列举 `prefix` 都相对于该目录；服务端会自行拼接真实应用路径。未绑定目录时，路径相对于应用根目录。

### 幂等请求头

创建上传会话、确认上传等写操作必须传入 8–128 字符的 `Idempotency-Key`：

```http
Idempotency-Key: upload-order-20260820-0001
```

同一业务动作重试时使用相同值；不同动作必须使用不同值。

### 统一错误格式

非 2xx 响应使用以下格式：

```json
{
  "code": "permission_denied",
  "message": "...",
  "request_id": "..."
}
```

常见错误包括：`authentication_required`（Key 无效/过期）、`permission_denied`（scope 或目录范围不允许）、`validation_failed`（参数不合法）、`invalid_idempotency_key`（幂等键不合法）和 `resource_not_found`（文件不存在或不可见）。

## 2. 查看文件

```http
GET /api/v1/application/files?application_code={application_code}&prefix={prefix}&status=available
Authorization: S3MP-Key <API_KEY>
```

参数：

| 参数 | 位置 | 必填 | 说明 |
| --- | --- | --- | --- |
| `application_code` | query | 是 | 调用方应用代码，例如 `postUser`。 |
| `prefix` | query | 否 | 按目录前缀筛选；不传表示列出 Key 可访问目录的全部文件。 |
| `status` | query | 否 | 文件状态，默认 `available`。 |

成功响应 `200 OK`：

```json
[
  {
    "id": "e5ef8489-d487-444f-a067-1eff8421c3b0",
    "storage_space_id": "3d373069-52ba-474e-aaa4-c76630ca85a1",
    "object_key": "sps/202608/0003_month.json",
    "content_length": 18936138,
    "content_type": "application/json",
    "status": "available",
    "etag": "db2e836d063c1810b9a9c2f4fa9ffe35",
    "checksum": null,
    "created_at": "2026-08-20T20:15:48.712324+08:00"
  }
]
```

下载时使用返回的 `id`，不要使用 `object_key` 拼接对象存储地址。

## 3. 上传文件（直传）

上传包含三个步骤：创建上传会话、向临时 URL 上传二进制内容、确认上传完成。

### 3.1 创建上传会话

```http
POST /api/v1/application/direct_uploads?application_code={application_code}
Authorization: S3MP-Key <API_KEY>
Idempotency-Key: upload-0003-month-json-20260820
Content-Type: application/json
```

请求体：

```json
{
  "object_key": "sps/202608/0003_month.json",
  "content_length": 18936138,
  "content_type": "application/json",
  "checksum": null,
  "expires_at": "2026-08-20T13:15:00Z"
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `object_key` | 是 | 文件路径；相对于 API Key 的目录范围。不得以 `/` 开头，也不得包含 `..`、反斜杠或物理存储前缀。 |
| `content_length` | 是 | 文件字节数，必须与实际上传内容一致。 |
| `content_type` | 是 | MIME 类型，例如 `application/json`、`text/markdown`。 |
| `checksum` | 否 | 可选完整性校验值；不使用时请省略或传 `null`。 |
| `expires_at` | 是 | 上传会话失效时间，UTC RFC 3339 格式，必须是未来时间。 |

成功响应 `201 Created`：

```json
{
  "id": "89b2eeb1-12ec-490e-9cc9-f6445a5e01a3",
  "storage_space_id": "3d373069-52ba-474e-aaa4-c76630ca85a1",
  "object_key": "sps/202608/0003_month.json",
  "content_length": 18936138,
  "content_type": "application/json",
  "status": "pending",
  "expires_at": "2026-08-20T13:15:00+00:00",
  "ingestion_id": "...",
  "mode": "direct",
  "method": "PUT",
  "url": "https://...短时预签名地址...",
  "headers": {
    "Content-Type": "application/json"
  }
}
```

`url` 是短时有效且敏感的预签名地址，不应写入日志或长期保存。

### 3.2 上传文件内容到预签名地址

使用上一步返回的 `method`、`url` 和 `headers` 原样发起请求。该请求直接到对象存储，**不需要**再传 S3MP 的 API Key 或 `application_code`。

```bash
curl -X PUT "$url" \
  -H "Content-Type: application/json" \
  --upload-file "0003_month.json"
```

请求成功时通常返回 `200` 或 `204`。

### 3.3 确认上传完成

```http
POST /api/v1/direct_uploads/{upload_id}/completion?application_code={application_code}
Authorization: S3MP-Key <API_KEY>
Idempotency-Key: complete-0003-month-json-20260820
Content-Type: application/json
```

请求体：

```json
{
  "checksum": null
}
```

成功响应 `200 OK`：

```json
{
  "id": "...",
  "status": "committed",
  "storage_space_id": "3d373069-52ba-474e-aaa4-c76630ca85a1",
  "etag": "db2e836d063c1810b9a9c2f4fa9ffe35",
  "file_object": {
    "id": "0ffea0be-852e-4245-91e3-7870cc53d08d",
    "object_key": "sps/202608/0003_month.json",
    "content_length": 18936138,
    "content_type": "application/json",
    "status": "available"
  }
}
```

平台会校验对象是否存在、对象大小和类型是否与创建会话时的声明一致；只有状态为 `committed` 且 `file_object.status` 为 `available` 时，文件才可被正常读取或下载。

## 4. 获取下载地址并下载文件

### 4.1 获取短时下载地址

先通过“查看文件”接口取得 `file_id`，然后请求：

```http
POST /api/v1/application/presigned_downloads?application_code={application_code}
Authorization: S3MP-Key <API_KEY>
Content-Type: application/json
```

请求体：

```json
{
  "file_id": "e5ef8489-d487-444f-a067-1eff8421c3b0",
  "ttl_seconds": 900
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file_id` | 是 | 文件列表返回的 `id`。 |
| `ttl_seconds` | 否 | 下载地址有效期，单位秒；范围 30–3600，默认 900。 |

成功响应 `201 Created`：

```json
{
  "method": "GET",
  "url": "https://...短时预签名地址...",
  "file_id": "e5ef8489-d487-444f-a067-1eff8421c3b0",
  "expires_in": 900
}
```

### 4.2 下载文件内容

使用响应中的 URL 直接发起 GET，不再传 S3MP API Key：

```bash
curl -L "$url" -o "260717-天河东大区覃应成交保利辰园湖镜-业主转客户运营-案例卡.md"
```

## 5. 完整流程示例

```text
1. GET  /application/files                         -> 获得 file_id，查看文件
2. POST /application/presigned_downloads           -> 获得短时下载 URL
3. GET  <预签名 URL>                                -> 下载文件

或：

1. POST /application/direct_uploads                -> 获得 upload_id 与 PUT URL
2. PUT  <预签名 URL>                                -> 上传文件字节
3. POST /direct_uploads/{upload_id}/completion      -> 文件提交为 available
```

## 6. 安全要求

- API Key、上传 URL、下载 URL 都是敏感凭据，禁止写入前端代码、Git、日志或工单。
- Key 只能按其 scope 和目录范围访问文件；目录范围外的请求会返回 `403 permission_denied`。
- 预签名 URL 在已签发后的有效期内可继续使用；如发生泄露，应立即撤销 API Key 并等待已发 URL 到期。
- 业务侧应记录平台返回的 `request_id`，便于问题排查。
