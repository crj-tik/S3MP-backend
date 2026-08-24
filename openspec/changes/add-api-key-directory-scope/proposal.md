## Why

现有 API Key 只能将文件访问定位到目标应用的整个存储命名空间，无法把交付给调用方的凭据收敛到应用内的指定目录。需要让一个 Key 可选地代表应用根目录或一个受限子目录，避免持有该 Key 的调用方读取、写入或删除同一应用中的其他目录。

## What Changes

- API Key 签发时增加可选的应用内“存取目录”范围；未指定时范围默认为目标应用的存储根目录。
- 指定目录时，系统只接受目标应用命名空间内的规范化相对目录；该 Key 的文件、上传、下载、删除、列举、预签名、multipart 与对象操作均限制在该目录及其子目录。
- 应用 API 的对象 key、列举前缀等输入改为相对于 Key 目录范围，由服务端拼接并验证实际应用内路径；调用方不能提交 Key 范围之外的应用内路径或物理对象 key。
- 在签发 Key 时持久化目录范围，并以平台对象存储的目录语义创建或登记该范围；空目录在对象存储不具备原生实体时，目录可由范围记录表示，前端不得把目录标记对象当作用户文件。
- 延迟执行、直传完成、multipart、预签名及续传操作复核同一 Key 的目录范围，防止用已有会话、上传 ID 或签名绕过目录限制。
- 保持既有目标/审计身份模型：API Key 决定目标应用和目录范围，`application_code` 仅表示同租户的操作应用并用于审计；浏览器端仍以 `application_id` 选择目标应用，不受 API Key 目录范围影响。

## Capabilities

### New Capabilities

- `api-key-directory-scope`: API Key 的应用内目录范围、默认根目录规则及其全链路强制执行。

### Modified Capabilities

- `backend-application-access`: 将 API Key 生命周期与权限交集扩展为包含 Key 自身的目录范围。
- `backend-file-storage`: 将应用 API 的路径解析、预签名、会话与异步复核限制到 Key 目录范围。
- `shared-s3-application-storage`: 明确应用命名空间内由服务端派生的 Key 目录前缀边界。

## Impact

- 后端 API Key 模型、迁移、签发生命周期服务、文件路由、路径规范化、对象存储适配、上传/multipart 会话和审计证据。
- OpenAPI 契约、生成客户端、API Key 管理界面和 Key 签发/详情展示。
- 应用 API 的文件路径和列举前缀语义，以及目录隔离、续传、预签名和跨应用审计的测试。
