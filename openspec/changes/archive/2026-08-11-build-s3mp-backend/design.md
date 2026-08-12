## Context

本 change 从总体架构 `design-multitenant-s3-management-platform` 中提取全部后端实施责任。后端需要先产生前端可消费的契约基线，再逐步实现身份授权和 S3 数据面；工作目录与前端隔离。

## Goals / Non-Goals

**Goals:**
- 交付可独立运行、迁移和测试的 Python API/Worker。
- 由后端拥有 `contracts/**`，保证契约与实现一致。
- 建立用户权限纵向闭环后再开放 S3 写能力。
- 仅修改独立后端仓库内的工程文件、`src/**`、`tests/**`、`contracts/**`、`deploy/**` 和本 change。

**Non-Goals:**
- 不创建或修改 Vue 前端。
- 不让浏览器或应用获得底层 S3 AK/SK。
- 不实现未验收的完整 AWS S3 功能。

## Decisions

### 1. 后端目录与模块

本 change 位于独立 `S3MP-backend` 仓库，采用根目录 `src/s3mp` 的 src layout，模块为 common、identity、tenant、authorization、applications、files、storage、audit、governance；每个模块分 domain、application、infrastructure、api。HTTP 层调用 application service，S3 SDK 只存在于 storage adapter。

### 2. 技术栈

Python 3.12 + uv + FastAPI + Pydantic + SQLAlchemy 2 + Alembic + PostgreSQL；Redis 负责限流、短期缓存与任务协调；pytest、类型检查和格式化形成质量门。异步任务采用可替换队列端口，先以 Redis 实现，避免领域代码绑定具体 Worker 框架。

### 3. 后端拥有契约

`contracts/openapi.yaml`、`api-conventions.md`、`error-codes.yaml`、`permission-catalog.yaml` 和 examples 由本 change 维护。先定义契约，运行时 OpenAPI 必须在 CI 与基线比较。契约提交与实现提交尽量分开，使前端 worktree 可先同步契约。

### 4. 用户授权优先纵向实现

第一条完整链路为本地登录 → `/me` → 用户/成员 → 用户组 → 角色/RoleBinding → 有效权限解释 → 暂停用户即时回收。授权模型采用 RBAC + storage space/canonical prefix scope；直接授权限期，authorization version 驱动缓存和会话重验。

### 5. 数据与租户约束

所有租户实体使用 tenant_id，关键关系使用 `(tenant_id,id)` 组合约束。Repository 方法必须接收 PrincipalContext/tenant_id。缓存、cursor、幂等键、任务载荷和审计均绑定 tenant。平台管理员和业务数据读取权限分离。

### 6. S3 数据面分阶段开启

先做显式 endpoint/region/SigV4/path-style 的只读连接与能力探测，再实现 canonical key 和 AuthorizedCommand，随后开放列表、预签名、代理上传、multipart 和对象状态机。写能力按连接 capability flag 和租户灰度。

### 7. Worktree 所有权

后端实施对话只能修改独立后端仓库内文件。不得修改仓库外的前端项目。契约改变后需输出变更摘要和兼容性影响，由前端同步已发布契约，不直接跨仓库协作未提交文件。

## Risks / Trade-offs

- [后端同时拥有契约与实现可能单方面破坏前端] → 契约优先提交、兼容检查、变更摘要和前端生成测试。
- [授权模块过度复杂] → 先完成固定系统角色和 scoped binding，再逐步开放自定义角色及 Access Review。
- [S3 环境不支持浏览器直传] → 能力探测后决定预签名或代理，不把 CORS 作为默认能力。
- [权限回收受缓存延迟影响] → authorization version、会话状态校验和高风险操作实时查询。
- [同一 change 范围较大] → 按任务阶段小批实施，每阶段保持可运行和可回滚。

## Migration Plan

1. 建立契约和后端骨架、健康检查、数据库/Redis 连接。
2. 实现用户权限纵向闭环并发布只读契约。
3. 验收 S3 连接并开放只读文件能力。
4. 实现应用 Key、上传、预签名和配额。
5. 实现 multipart、移动/删除、Access Review 和治理。
6. 联合前端进行契约和端到端验收。

回滚时按 capability flag 禁用新能力；数据库迁移采用向前兼容扩展，避免自动删除对象和审计数据。
