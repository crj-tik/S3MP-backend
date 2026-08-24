## Why

当前应用 API Key 的身份同时被当作目标存储应用和操作审计主体，导致持有目标应用 Key 的其他同租户应用无法被准确记录为操作来源，也限制了明确授权的跨应用协作。

## What Changes

- 应用数据面以 API Key 所属应用作为目标应用，服务端据此解析唯一的应用存储命名空间。
- 应用数据面请求必须携带 `application_code`，用于解析同租户的操作应用并写入审计；该 code 不再用于选择目标目录。
- **BREAKING** 应用 API Key 调用文件、上传、下载、删除、对象操作和 multipart 数据面时，`application_code` 的语义由“目标应用”改为“操作应用”。
- 浏览器管理端的数据面继续使用内部 `application_id` 选择目标应用，并将当前登录用户记录为操作主体。
- 删除 API Key 所属应用必须与请求 code 所属应用相同的限制；不存在、失效或跨租户的 code 必须被拒绝且不得访问对象存储。
- 审计和持久化记录目标应用与操作应用/用户，支持区分资源归属和发起者。

## Capabilities

### New Capabilities

- `application-data-plane-actor-attribution`: 将应用 API Key 的目标命名空间与请求声明的操作应用审计主体分离。

### Modified Capabilities

- `backend-file-storage`: 修改应用数据面寻址、授权和审计主体规则。
- `backend-application-access`: 修改 API Key 在同租户跨应用协作时的权限边界。
- `shared-s3-application-storage`: 修改 API Key 应用命名空间的跨应用请求约束。

## Impact

- 后端文件路由、文件服务、应用/存储查询、审计与上传/操作持久化模型。
- OpenAPI 契约、前端浏览器数据面调用和 API 文档。
- 文件、上传、下载、删除、multipart、异步对象操作的授权与端到端测试。
