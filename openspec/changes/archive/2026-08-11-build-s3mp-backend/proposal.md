## Why

总体方案已确定多租户 S3 管理平台的安全与领域边界，但后端需要独立的实施生命周期，以便在专用对话和 worktree 中完成 Python 服务、共享 API 契约、权限系统与 S3 数据面，而不与前端工程相互修改。

## What Changes

- 在独立 `S3MP-backend` 仓库根目录建设 Python 3.12/FastAPI 模块化单体 API 与独立 Worker，源码采用 `src/s3mp/**` 布局。
- 后端独占维护 `contracts/**`，优先交付 OpenAPI、API 约定、稳定错误码、权限目录和 Mock 示例，作为前端只读契约。
- 实现 PostgreSQL/Redis 基础设施、多租户身份、用户组、角色、scoped RoleBinding、有效权限解释、权限回收与 Access Review。
- 实现第三方应用与平台 API Key 生命周期、目录授权、文件对象、预签名、multipart、配额与审计。
- 封装公司 S3 子集，强制 SigV4、path-style、显式 endpoint/region、连接级能力探测和兼容开关。
- 后端仅修改独立仓库内的工程文件、`src/**`、`tests/**`、`contracts/**`、`deploy/**` 及本 change；不修改仓库外的前端项目。

## Capabilities

### New Capabilities
- `backend-api-contract`: 后端拥有的版本化 REST/OpenAPI、错误码、权限目录及契约兼容行为。
- `backend-identity-authorization`: 多租户身份、用户组、角色、资源范围授权、有效权限解释和权限生命周期。
- `backend-application-access`: 应用主体、API Key、scope、限流、轮换与吊销。
- `backend-file-storage`: 文件对象、预签名、multipart、S3 子集适配、配额、状态机与审计。

### Modified Capabilities

无；本 change 实施总体方案中的后端能力，不修改已归档主规格。

## Impact

- 在独立仓库新增根工程文件、`src/**`、`tests/**`、`contracts/**` 和 `deploy/**`。
- 引入 Python/FastAPI、SQLAlchemy/Alembic、PostgreSQL、Redis、S3 SDK 和后端测试工具链。
- `contracts/**` 成为前端生成类型、API Client 与 Mock 的唯一接口来源。
- 不新增或修改前端实现文件；前端契约问题通过变更请求反馈给后端 change。
