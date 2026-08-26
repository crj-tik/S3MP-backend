# 第三方应用文件接入指南（生产环境）

本文面向第三方应用，说明如何通过 S3MP 应用 API Key 查看文件、上传文件和下载文件。本文只覆盖应用间 API 调用；管理后台登录、租户管理和 API Key 创建由 S3MP 管理员完成。

## 1. 基本约定

### 生产服务地址

生产 API 根地址：

```text
https://gz-ai.ke.com/s3mp
```

以下示例使用环境变量，避免在业务代码中散落服务地址和密钥：

```bash
export S3MP_API_BASE_URL='https://gz-ai.ke.com/s3mp'
export S3MP_API_KEY='<平台分配的 API Key>'
export S3MP_APPLICATION_CODE='<调用方应用代码>'
```

接口文档中的 `/api/v1/...` 均为相对路径；实际请求地址必须以前述根地址为前缀，例如：

```text
GET https://gz-ai.ke.com/s3mp/api/v1/application/files
```

不要改为直接访问服务器 IP、Docker 端口、对象存储 bucket 或物理对象路径。

### 接入前由平台管理员提供

第三方上线前，请向 S3MP 管理员确认并获取：

1. 调用方 `application_code`。
2. 仅展示一次的应用 API Key（格式为 `sk_...`）；请通过密钥管理系统或部署变量保存。
3. API Key 对应的目标应用、允许操作（读取、写入、删除、移动）及可访问目录范围。
4. 测试用的非敏感文件路径和验收时段。

API Key 只代表一个应用身份；不得使用平台账号密码、浏览器 Cookie、S3 AK/SK 或其他应用的 Key 调用本接口。

### 一个应用可签发多把 API Key

一个应用**可以同时配置多把 API Key**，没有“一应用只能一把 Key”的限制。每把 Key 都是独立凭据，可以分别设置名称/用途、有效期、权限集合和可访问目录；撤销或轮换其中一把不会影响同一应用的其他 Key。

但每个应用最多保留 **20 把有效 API Key**。这 20 把 Key 是应用级集成凭据配额，不应用于“每位员工一把 Key”的个人身份管理；员工应通过管理后台账号、用户组和角色授权访问平台。API Key 应按系统、环境或自动化任务等稳定集成边界分配。

达到上限前，应先撤销不再使用的 Key，再签发新的 Key；Key 轮换时也应预留一个名额用于旧 Key 与新 Key 的短暂重叠。

建议按调用方和用途拆分，例如：

| Key 用途 | 建议权限 | 目录范围示例 | 说明 |
| --- | --- | --- | --- |
| 报表生产系统 | `files.write`、`files.list` | `reports/` | 仅上传及检查报表文件。 |
| 文件下载服务 | `files.list`、`presigned_urls.issue` | `published/` | 仅列出并签发下载链接，不能写入或删除。 |
| 数据清理任务 | `files.list`、`files.delete` | `temporary/` | 仅处理临时目录；应使用短有效期 Key。 |
| 日常运维集成 | 按需组合 | 应用根目录或指定目录 | 不建议授予超出实际用途的权限。 |

每次请求的有效权限取以下约束的交集：**该 Key 的权限集合**、**该 Key 的目录范围**、**应用授权代表拥有的租户角色与目录授权**。因此，一把目录受限的 Key 不会因同一应用存在另一把高权限 Key 而扩大权限。

### 文件操作权限

| 权限点 | 允许的文件操作 |
| --- | --- |
| `files.list` | 按 `prefix` 列举可访问文件。 |
| `files.read` | 读取文件元数据、上传会话或文件处理溯源等读取型资源。 |
| `files.write` | 创建直传/分片上传会话、上传分片、完成上传、取消上传等写入型操作。 |
| `files.delete` | 删除文件或执行涉及删除源文件的操作。 |
| `files.move` | 重命名文件；同时仍须具备源路径的读取/删除和目标路径的写入权限。 |
| `presigned_urls.issue` | 为有权访问的文件签发短时下载 URL；该权限不等于直接写入或删除文件。 |

第三方通常不需要 `files.delete`。下载场景通常同时需要 `files.list`（获得 `file_id`）和 `presigned_urls.issue`（签发下载 URL）。

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

### 指定文件路径与目录范围

上传文件时由调用方在 `object_key` 指定逻辑文件路径；这不是随机生成的文件名，也不是物理对象存储路径。例如：

```json
{
  "object_key": "orders/2026/08/order-10001.json"
}
```

如果 Key 在创建时绑定了“存取目录”，上传 `object_key` 和查询 `prefix` 都是**相对于该目录**的路径，服务端会自行拼接真实应用路径。例如 Key 被限制在 `reports/`：

| 调用方输入 | 服务端实际可访问的逻辑范围 |
| --- | --- |
| `object_key: "daily/2026-08-25.csv"` | `reports/daily/2026-08-25.csv` |
| `prefix: "daily/"` | `reports/daily/` 下的文件 |
| `object_key: "../other/a.csv"` | 拒绝，不能跳出目录范围。 |

未绑定目录时，路径相对于应用根目录。`object_key` 不得以 `/` 开头，不得包含 `..`、反斜杠或 bucket/物理对象前缀；不要让用户输入直接成为对象路径。

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

常见错误包括：`authentication_required`（Key 无效/过期）、`permission_denied`（scope 或目录范围不允许）、`validation_failed`（参数不合法）、`precondition_failed`（文件 ETag 已变化）、`duplicate_resource`（目标路径已存在）、`rename_conflict`（源文件已有进行中的重命名）、`invalid_idempotency_key`（幂等键不合法）和 `resource_not_found`（文件不存在或不可见）。

## 2. 查看文件

```bash
curl -sS -G "$S3MP_API_BASE_URL/api/v1/application/files" \
  -H "Authorization: S3MP-Key $S3MP_API_KEY" \
  --data-urlencode "application_code=$S3MP_APPLICATION_CODE" \
  --data-urlencode 'prefix=reports/' \
  --data-urlencode 'status=available'
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
| `expires_at` | 是 | 上传会话失效时间，Asia/Shanghai（UTC+08:00）格式，必须是未来时间。 |

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

## 5. 重命名文件

重命名不会把文件内容下载到调用方后再上传。平台在后台执行对象存储的 copy、校验和删源，因此该接口始终是异步的。重命名成功后，**原 `file_id` 不再可用于读取或下载**，请使用响应及操作状态中返回的新 `file_id`。

前提：API Key 在源路径具备 `files.move`、`files.read`、`files.delete`，并在目标路径具备 `files.write`；两个路径都必须落在该 Key 的目录范围内。

```http
POST /api/v1/application/files/{file_id}/rename?application_code={application_code}
Authorization: S3MP-Key <API_KEY>
If-Match: <当前文件的 etag>
Idempotency-Key: rename-order-10001-20260825
Content-Type: application/json
```

请求体中的目标路径与上传时相同，均相对于 API Key 的目录范围：

```json
{
  "object_key": "orders/2026/08/order-10001-final.json"
}
```

成功受理时返回 `202 Accepted`：

```json
{
  "operation_id": "df8c68fb-5fa8-43d2-9507-27c4b62fa5fa",
  "status": "pending",
  "file": {
    "id": "a98a0664-8e22-4dfd-96f1-96a13cf9d43d",
    "object_key": "orders/2026/08/order-10001-final.json",
    "status": "renaming"
  }
}
```

立即保存 `file.id`，但在操作成功前不得读取或下载该文件。使用操作查询接口轮询结果：

```bash
curl -sS -G "$S3MP_API_BASE_URL/api/v1/application/file_operations/$OPERATION_ID" \
  -H "Authorization: S3MP-Key $S3MP_API_KEY" \
  --data-urlencode "application_code=$S3MP_APPLICATION_CODE"
```

当响应的 `status` 为 `succeeded` 时，`result_file_id` 即为可用的新文件 ID。若为 `partial_failure`，平台已完成目标 copy 但尚未确认删除源文件，会自动或由运维恢复；不要重发不同幂等键的重命名请求，也不要把该操作当作成功。

同一业务重试必须使用完全相同的 `Idempotency-Key`、源 `file_id`、`If-Match` 和目标路径；平台将返回原 operation/new file ID。相同幂等键改成其他目标路径会返回 `409 idempotency_conflict`。

## 6. 完整流程示例

```text
1. GET  /application/files                         -> 获得 file_id，查看文件
2. POST /application/presigned_downloads           -> 获得短时下载 URL
3. GET  <预签名 URL>                                -> 下载文件

或：

1. POST /application/direct_uploads                -> 获得 upload_id 与 PUT URL
2. PUT  <预签名 URL>                                -> 上传文件字节
3. POST /direct_uploads/{upload_id}/completion      -> 文件提交为 available

或：

1. GET  /application/files                          -> 获得当前 file_id 与 etag
2. POST /application/files/{file_id}/rename         -> 获得 operation_id 与新的 file_id
3. GET  /application/file_operations/{operation_id} -> 等待 status=succeeded
4. 使用 result_file_id 进行下载或后续文件操作
```

## 7. 上线验收清单

1. 使用生产根地址 `https://gz-ai.ke.com/s3mp`，不要使用 IP、`localhost` 或 Docker 端口。
2. 以最小权限 API Key 调用一次文件列表，确认返回 `200` 且仅包含授权目录内容。
3. 上传一个非敏感小文件，完成确认后下载并校验字节数、内容类型和业务摘要。
4. 对同一写操作重试时复用同一个 `Idempotency-Key`，确认不会创建重复文件。
5. 记录失败响应中的 `request_id`；排障时提供该值、请求时间、接口路径和状态码，绝不提供 API Key 或预签名 URL。
6. 验收完成后删除测试文件，或按双方约定保留并标记为测试数据。
7. 使用专用测试文件验证重命名：确认返回新的 file ID、旧 ID 不再可读、目标在成功前不出现在文件列表中；再验证同一幂等键重试不会创建第二个目标文件。

## 8. 安全要求

- API Key、上传 URL、下载 URL 都是敏感凭据，禁止写入前端代码、Git、日志或工单。
- Key 只能按其 scope 和目录范围访问文件；目录范围外的请求会返回 `403 permission_denied`。
- 预签名 URL 在已签发后的有效期内可继续使用；如发生泄露，应立即撤销 API Key 并等待已发 URL 到期。
- 业务侧应记录平台返回的 `request_id`，便于问题排查。

## 9. 删除保留期与恢复

删除文件后，平台会立即将该文件从 API Key 的列表、元数据查询、下载签名、重命名和后续删除操作中隐藏；对象内容及配额会保留 **三个自然月**。例如 11 月 30 日删除的文件，到次年 2 月的最后一天同一北京时间到期。

保留期内，原文件路径仍被占用，不能用上传或重命名覆盖；第三方应用再次以该文件 ID 或路径请求资源时统一得到 `404 resource_not_found`，不会暴露保留期或对象存储信息。

恢复仅能由租户管理平台中拥有 `files.delete` 权限的人工主体执行，且必须在到期前提供原文件 ETag 与幂等键。API Key 不能调用恢复接口。到期后，后台会在北京时间凌晨清理对象并释放配额，已物理清理的文件不能恢复。
