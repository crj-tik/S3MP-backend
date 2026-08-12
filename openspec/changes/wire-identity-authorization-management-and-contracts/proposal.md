## Why

身份和授权管理路由已经公开且被 OpenAPI 声明，但生产应用生命周期未装配其管理服务，认证后的请求会失败为 500。现有契约检查只覆盖路由外形，不能发现成功响应字段、授权语义和真实持久化流程的漂移，前端无法安全依赖这些接口。

## What Changes

- 装配数据库驱动的身份管理、授权管理和当前主体上下文服务，使公开管理端点在生产生命周期可执行。
- 完整持久化角色权限、成员、组、角色绑定与授权解释所需的数据，并在所有资源读取和变更中强制租户边界、权限与委派约束。
- 为身份与授权管理端点定义严格的请求/响应 DTO、分页、ETag 和错误行为，使运行时响应与 `contracts/openapi.yaml` 对齐。
- 使契约校验比较成功响应 schema，并添加不依赖 fake service 注入的真实数据库端到端覆盖。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `backend-identity-authorization`: 身份、成员、组、角色和角色绑定管理必须在生产装配中实际执行，并强制租户隔离、授权与可解释的权限决策。
- `backend-api-contract`: 公开身份授权端点的成功响应、分页、并发前置条件和错误必须由严格 DTO 与运行时行为兑现。
- `runtime-contract-enforcement`: 自动契约检查必须检测公开成功响应 schema 与基线契约的漂移，并以真实装配的端到端测试防止 fake service 掩盖缺陷。

## Impact

- 影响 `src/s3mp/main.py`、identity/authorization 的 API、application 和 infrastructure 层，以及认证和授权依赖。
- 影响 PostgreSQL 查询、角色权限关联、会话回收、审计与 ETag 计算。
- 影响 `contracts/openapi.yaml`、契约校验脚本和真实基础设施测试；不引入新的外部基础设施。
