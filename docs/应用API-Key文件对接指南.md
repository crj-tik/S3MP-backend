# 第三方应用文件接入指南（生产环境）

本文说明第三方服务如何使用 S3MP 应用 API Key 列表、上传、下载、更新元数据、删除和重命名文件。管理后台中的应用、角色、API Key 签发与轮换不属于本文范围。

## 1. 接入约定

生产 API 根地址：

```text
https://gz-ai.ke.com/s3mp
```

建议将地址、凭据和调用方应用代码放在部署变量中：

```bash
export S3MP_API_BASE_URL='https://gz-ai.ke.com/s3mp'
export S3MP_API_KEY='<平台签发的完整凭据>'
export S3MP_APPLICATION_CODE='<调用方应用代码>'
```

除对象存储预签名 URL 外，所有 S3MP 请求都使用：

```http
Authorization: S3MP-Key <API_KEY>
```

`/api/v1/application/...` 路径都必须带查询参数 `application_code`。直传完成接口 `POST /api/v1/direct_uploads/{upload_id}/completion` 也必须带该参数。以 `upload_id`、`multipart_id` 或 `operation_id` 定位的其他后续接口不带 `application_code`。

API Key 决定目标应用和授权目录；`application_code` 必须是该目标应用在同一租户内的有效代码。服务端会将它记录为操作主体，并用于上传会话的归属校验；因此不要用其他应用的代码代替。调用方不得传递 `application_id`、租户 ID、bucket 或物理对象路径。

API Key 的明文仅在签发或轮换时返回一次。一个应用可以有多把 Key；当前实现可分别设置权限集合、有效期和可选目录范围。不要假设存在未在管理接口或合同中声明的 Key 数量配额、名称字段或用途字段。

## 2. 权限与路径

每个请求同时受 API Key 权限、Key 的可选目录范围以及目标应用在存储空间中的角色绑定限制；任一约束不满足都会被拒绝。

| 权限 | 用途 |
| --- | --- |
| `files.list` | 列出文件。 |
| `files.read` | 获取文件详情、查询异步文件操作、读取上传溯源。 |
| `files.write` | 上传预检、创建/查询/完成/中止上传会话、上传分片、修改元数据。 |
| `files.delete` | 删除文件；重命名时还需要源路径的此权限。 |
| `files.move` | 重命名源文件。 |
| `presigned_urls.issue` | 为文件签发下载 URL。 |

重命名还需要源路径的 `files.read`、`files.delete`、`files.move`，以及目标路径的 `files.write`。

`object_key` 和 `prefix` 均是逻辑相对路径，不是对象存储物理路径。若 Key 的目录范围为 `reports/`，调用方输入 `daily/a.csv` 实际访问的是 `reports/daily/a.csv`；文件响应中的 `object_key` 是相对应用根目录的逻辑路径，例如 `reports/daily/a.csv`。路径不得以 `/` 开头，不得包含 `..` 或反斜杠。

## 3. 文件标识与版本字段

文件响应包含内部 UUID `id`，并可能包含公开引用 `file_ref`：

| 字段 | 用途 |
| --- | --- |
| `file_ref` | 新客户端优先使用的公开文件引用。它由应用范围、相对路径、规范化元数据和已验证的 SHA-256 生成；路径或元数据变化后会改变。 |
| `id` / 请求字段 `file_id` | UUID 兼容轨。`file_id` 是历史请求字段名，但可以传入 UUID 或 `file_ref`。 |
| `etag` | 对象存储内容版本。UUID 兼容轨的删除和重命名用它作为 `If-Match`。 |
| `record_etag` | 文件记录版本。仅用于修改元数据的 `If-Match`。 |

新客户端应在响应有 `file_ref` 时保存它；若历史文件的 `file_ref` 为 `null`，暂时保存并使用 UUID。不要自行构造 `file_ref`，也不要把 `etag` 当作文件 ID。

历史文件的 `file_ref` 回填由平台运维任务执行，不是调用接口时自动触发的后台操作。回填完成前 UUID 兼容轨仍可用。

所有写操作都需要 8–128 字符的 `Idempotency-Key`。同一业务动作的网络重试必须复用完全相同的值；不同业务动作使用不同值。

```http
Idempotency-Key: upload-order-10001-v1
```

## 4. 常用接口

以下路径均相对于 `$S3MP_API_BASE_URL/api/v1`。表中 `/application/...` 接口均须加 `?application_code=$S3MP_APPLICATION_CODE`。

| 操作 | 方法与路径 | 关键输入 | 成功后处理 |
| --- | --- | --- | --- |
| 列表 | `GET /application/files` | 可选 `prefix`、`status` | 保存 `file_ref`，或在其为空时保存 UUID。 |
| 文件详情 | `GET /application/files/{file_id}` | UUID 或 `file_ref` | 获取当前文件字段及版本字段。 |
| 元数据替换 | `PATCH /application/files/{file_id}/metadata` | `If-Match: record_etag`、`Idempotency-Key`、`metadata` | 用响应中的新 `record_etag` 覆盖本地值；`file_ref` 非空时一并更新。 |
| 名称预检 | `POST /application/upload_prechecks` | `object_key`、`content_length` | 仅作重名提示，最终以创建和完成上传的服务端校验为准。 |
| 创建直传 | `POST /application/direct_uploads` | `Idempotency-Key`、路径、大小、类型、带时区的过期时间 | 保存 `upload_id`，按原样使用返回的上传方法、URL 和 headers。 |
| 查询直传 | `GET /direct_uploads/{upload_id}` | `upload_id` | 未过期时返回可用的直传信息。 |
| 完成直传 | `POST /direct_uploads/{upload_id}/completion` | `application_code`、`Idempotency-Key` | 只在响应有可用 `file_object` 后保存文件引用。 |
| 下载 URL | `POST /application/presigned_downloads` | `file_id`（UUID 或 `file_ref`）、可选 `ttl_seconds` | 仅短期使用返回的 URL。 |
| 删除 | `DELETE /application/files/{file_id}` | `Idempotency-Key`；UUID 轨额外带 `If-Match: etag` | `202` 后将本地记录标为删除已请求。 |
| 重命名 | `POST /application/files/{file_id}/rename` | 新路径、`Idempotency-Key`；UUID 轨额外带 `If-Match: etag` | 保存 `operation_id` 和目标引用，等待操作成功。 |

对于大文件，还可使用 `POST /application/multipart_uploads` 创建分片会话；之后通过 `/multipart_uploads/{multipart_id}`、`/parts` 和 `/completion` 继续操作。每个分片上传及分片完成都需要 `Idempotency-Key`；分片上传使用二进制 body 和正确的 `Content-Length`。当前响应的 `part_size` 为 8 MiB，完成请求提交服务端返回的、有序且不重复的 `parts[{part_number, etag}]`。

## 5. 查看文件与下载

```bash
curl -sS -G "$S3MP_API_BASE_URL/api/v1/application/files" \
  -H "Authorization: S3MP-Key $S3MP_API_KEY" \
  --data-urlencode "application_code=$S3MP_APPLICATION_CODE" \
  --data-urlencode 'prefix=reports/' \
  --data-urlencode 'status=available'
```

典型响应字段如下：

```json
[
  {
    "id": "e5ef8489-d487-444f-a067-1eff8421c3b0",
    "file_ref": "s3mpf1_<opaque-reference>",
    "object_key": "reports/2026/summary.json",
    "content_length": 18936138,
    "content_type": "application/json",
    "status": "available",
    "etag": "<provider-etag>",
    "record_etag": "<record-version>",
    "checksum": "sha256:<64-lowercase-hex>"
  }
]
```

获取下载 URL 时，请把所选标识放入保持兼容名称的 `file_id` 字段：

```bash
curl -sS -X POST "$S3MP_API_BASE_URL/api/v1/application/presigned_downloads?application_code=$S3MP_APPLICATION_CODE" \
  -H "Authorization: S3MP-Key $S3MP_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"file_id":"s3mpf1_<opaque-reference>","ttl_seconds":900}'
```

`ttl_seconds` 默认 900，范围为 30–3600 秒。返回的 URL 只能在有效期内直接 GET；不要在下载请求中附加 API Key，也不要长期保存或记录该 URL。

## 6. 直传上传

名称预检是推荐的交互步骤，不是占位锁。若响应 `exists: true`，调用方应选择其他最终路径并在自身业务库中保存该最终路径；即使预检返回 `false`，并发请求仍可能抢先占用同一路径。

```bash
curl -sS -X POST "$S3MP_API_BASE_URL/api/v1/application/upload_prechecks?application_code=$S3MP_APPLICATION_CODE" \
  -H "Authorization: S3MP-Key $S3MP_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"object_key":"reports/2026/summary.json","content_length":18936138}'
```

创建会话：

```bash
curl -sS -X POST "$S3MP_API_BASE_URL/api/v1/application/direct_uploads?application_code=$S3MP_APPLICATION_CODE" \
  -H "Authorization: S3MP-Key $S3MP_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: upload-summary-2026-v1' \
  --data '{
    "object_key":"reports/2026/summary.json",
    "content_length":18936138,
    "content_type":"application/json",
    "metadata":{"report_year":2026},
    "expires_at":"2099-01-01T00:00:00Z"
  }'
```

`expires_at` 必须是未来时间且包含时区；UTC（`Z`）和带偏移量的 RFC 3339 时间均可。`checksum` 可省略；服务端会在完成时计算 SHA-256。若调用方提供 `checksum`，必须是 SHA-256，且完成验证时必须与实际内容一致。

创建响应包含 `id`（即 `upload_id`）、`method`、`url` 和 `headers`。向返回的预签名 URL 上传时，必须原样携带所有返回 headers；这次对象存储请求不携带 S3MP API Key 或 `application_code`。

```bash
curl -X PUT "$UPLOAD_URL" \
  -H 'Content-Type: application/json' \
  --upload-file 'summary.json'
```

如果响应 `headers` 中还返回了校验头，也必须一并传递。

上传对象后确认完成：

```bash
curl -sS -X POST "$S3MP_API_BASE_URL/api/v1/direct_uploads/$UPLOAD_ID/completion?application_code=$S3MP_APPLICATION_CODE" \
  -H "Authorization: S3MP-Key $S3MP_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: complete-summary-2026-v1' \
  --data '{}'
```

服务端验证对象存在、大小和内容类型，并对正文计算 SHA-256。仅当完成响应中的 `file_object` 存在且其 `status` 为 `available` 时，才保存其中的 `file_ref`（或 UUID）并允许后续下载。对于 UUID 兼容轨，同时保存返回的 `etag`，供删除或重命名使用。

## 7. 更新元数据

元数据更新会整体替换当前 `metadata`；传入 `null` 会清空它。必须使用 `record_etag`，不能使用对象 `etag`。

```bash
curl -sS -X PATCH "$S3MP_API_BASE_URL/api/v1/application/files/$FILE_REF/metadata?application_code=$S3MP_APPLICATION_CODE" \
  -H "Authorization: S3MP-Key $S3MP_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'If-Match: <record_etag>' \
  -H 'Idempotency-Key: metadata-summary-2026-v2' \
  --data '{"metadata":{"report_year":2026,"source":"batch"}}'
```

成功后用响应的 `record_etag` 更新本地版本；若返回新的非空 `file_ref`，也要替换本地引用。收到 `412` 时，重新读取文件，合并业务数据后以新的幂等键发起新的业务动作。

## 8. 删除与重命名

删除接口立即受理并从正常的列表、详情和下载入口隐藏文件；物理对象会在三个月自然月的保留期结束后由平台异步清理。因此 `202 Accepted` 不代表对象已经物理删除。

新轨使用 `file_ref`，无需 `If-Match`：

```http
DELETE /api/v1/application/files/s3mpf1_<opaque-reference>?application_code={application_code}
Authorization: S3MP-Key <API_KEY>
Idempotency-Key: delete-summary-2026-v1
```

UUID 兼容轨需要当前对象 `etag`：

```http
DELETE /api/v1/application/files/{uuid}?application_code={application_code}
Authorization: S3MP-Key <API_KEY>
If-Match: <etag>
Idempotency-Key: delete-summary-2026-v1
```

重命名始终异步。新轨同样以 `file_ref` 替代路径中的 UUID 并省略 `If-Match`；UUID 兼容轨必须提供当前 `etag`。

```http
POST /api/v1/application/files/{file_id}/rename?application_code={application_code}
Authorization: S3MP-Key <API_KEY>
If-Match: <uuid-compatibility-track-etag>
Idempotency-Key: rename-summary-2026-v1
Content-Type: application/json
```

```json
{
  "object_key": "reports/2026/summary-final.json"
}
```

`202` 响应包含 `operation_id` 和预创建的目标 `file`。可立即保存目标的 `file_ref`（为空时保存 UUID）用于关联业务记录，但该文件的 `status=renaming` 时尚不可读取、下载、删除或再次重命名。查询操作直到 `status=succeeded`，并确认目标文件已 `available` 后，才将它作为可用文件。

```bash
curl -sS -G "$S3MP_API_BASE_URL/api/v1/application/file_operations/$OPERATION_ID" \
  -H "Authorization: S3MP-Key $S3MP_API_KEY" \
  --data-urlencode "application_code=$S3MP_APPLICATION_CODE"
```

`queued`、`processing`、`retry_scheduled` 表示尚未完成；`succeeded` 才能使用目标文件。`failed`、`cancelled`、`dead_lettered` 和 `partial_failure` 都需要按 `failure_reason` 处理，不能把目标当作可下载文件。使用同一幂等键重试同一重命名请求；同一 Key 搭配不同源或目标会得到 `409` 冲突。

## 9. 错误处理与上线验收

错误响应统一包含 `code`、`message` 和 `request_id`。常见状态包括：

| 状态 | 常见原因 | 建议处理 |
| --- | --- | --- |
| `401 authentication_required` | Key 无效、过期或已撤销。 | 更新凭据，不要重试旧 Key。 |
| `403 permission_denied` / `role_not_configured` | Key scope、目录范围或角色绑定不足。 | 由管理员调整授权。 |
| `409` | 路径已占用、上传/文件操作进行中、幂等键复用但请求不同。 | 按业务状态处理，不要盲目换 Key 重发。 |
| `412` | UUID 兼容轨的对象 `etag` 或元数据 `record_etag` 已过期。 | 重新读取后发起新的业务动作。 |
| `422 validation_failed` | 路径、过期时间、请求体等不合法。 | 修正请求。 |
| `404 resource_not_found` | 文件、上传会话或操作不可见/不存在。 | 以本地状态和业务幂等记录处理。 |

上线前至少验证以下项目：

1. 使用最小权限 Key 列表查询，确认结果仅限授权目录。
2. 直传一个非敏感小文件，确认完成响应含 `file_object.status=available`，再经预签名 URL 下载并校验内容。
3. 对同一创建、完成、删除或重命名请求重放相同 `Idempotency-Key`，确认不会产生重复业务结果。
4. 验证 UUID 兼容轨的 `If-Match` 过期会返回 `412`，并验证 `file_ref` 轨无需对象 `etag` 即可删除或重命名。
5. 验证重命名的目标在操作成功前不可下载，成功后改用目标引用。
6. 排障时仅提供 `request_id`、请求时间、路径和状态码；绝不提供 API Key 或预签名 URL。

## 10. 安全要求

- API Key、上传 URL 和下载 URL 都是敏感凭据，禁止提交到 Git、前端代码、日志或工单。
- 不要直接访问服务器 IP、Docker 端口、对象存储 bucket 或物理对象路径。
- 预签名 URL 在其有效期内独立生效；如发生泄露，应撤销相应 API Key，并等待已经签发的 URL 自行过期。
