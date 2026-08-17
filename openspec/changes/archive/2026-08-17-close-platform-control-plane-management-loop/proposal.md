## Why

平台控制面已具备平台角色、租户生命周期和限时 Support Access 的基础模型，但管理 API 只有局部写操作。平台管理员无法可靠发现账户、角色绑定、待审批支持访问或平台审计记录；更严重的是内置 `platform_admin` 缺少租户读取权限，无法读取租户列表。平台控制面与租户业务面因此不能形成安全、可审计的端到端管理流程。

## What Changes

- 修复平台内置角色的读取权限，并以幂等方式收敛已初始化数据库中的内置角色权限。
- 增加平台账户目录、平台角色及其绑定、Support Access 申请和平台审计的只读分页接口。
- 补全平台租户列表、详情和更新接口的明确响应 DTO，新增平台角色绑定与 Support Access 列表接口。
- 补全 S3 连接探测结果响应 DTO，禁止以请求 DTO 或 `unknown` 作为响应契约。
- 将创建租户的初始管理员选择、平台角色授予和 Support Access 审批建立在可查询的全局账户目录之上。
- 明确平台账户会话、租户 Membership 和 Support Access 的边界：平台权限不自动授予租户数据权限；跨租户查看业务数据必须通过双人审批、限时、只读的 Support Access 物化租户 Membership 后显式选择租户。
- 将 Support Access 到期回收纳入受管部署运行方式，确保到期后撤销 Membership、RoleBinding 与有效租户会话，并留下平台审计记录。
- 更新 OpenAPI、中文 Swagger 说明、部署文档和前端控制台对接所需的稳定响应模型与分页语义。
- 对所有新增和修复的接口执行运行时 OpenAPI 与 `contracts/openapi.yaml` 双向校验。
- 收敛实施后审计发现的控制面正确性缺口：所有列表必须在持久层完成筛选并执行真实分页，游标必须绑定筛选条件；状态筛选必须拒绝非法值；Support Access 响应必须包含安全的审批人摘要；每个路由必须声明其准确的操作标识；调度器健康检查必须实际验证一次到期回收执行能力。

## Capabilities

### New Capabilities

- `platform-control-plane-management`: 平台账户、内置平台角色、租户生命周期、Support Access 和平台审计的可发现、可操作、可回收管理闭环。

### Modified Capabilities

- `platform-control-plane`: 平台控制面增加显式读取能力、内置角色权限收敛与可验证的 Support Access 到期回收。
- `backend-api-contract`: 平台控制面新增分页 HTTP 操作和稳定 DTO，成为前端的规范契约。

## Impact

- 影响 `src/s3mp/platform/` 中的平台仓储、服务、路由、内置角色基线与审计模型查询。
- 影响 `src/s3mp/main.py`、部署 Compose/worker 或定时任务配置以及 `scripts/expire_support_access.py` 的运行方式。
- 影响 `contracts/openapi.yaml`、API 文档、权限目录和前端平台管理控制台。
- 影响平台控制面游标编码、账户/角色/租户/Support Access 查询、路由依赖标识、调度器入口及 Compose 健康检查。
- 需要数据库数据迁移或启动期幂等收敛，以为既有 `platform_admin` 角色补充缺失权限而不覆盖用户自定义角色。
