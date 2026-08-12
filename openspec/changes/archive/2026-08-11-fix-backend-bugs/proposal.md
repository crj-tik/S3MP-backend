## Why

2026-08-11 的 explore 排查发现了 8 个 bug，涵盖迁移遗漏、类型缺失、逻辑缺陷和代码质量问题。需要在继续开发前修复，避免后续 autogenerate 迁移遗漏表、契约漂移检测不完整、以及多 membership 场景下权限选择错误。

## What Changes

- 修复 `migrations/env.py` 缺少 `access_review_models` 导入，确保 autogenerate 能检测到 access_review 等 3 张表
- 修复 `scripts/check_openapi.py` 缺少反向检查，确保基线定义的端点运行时都有实现
- 修复 `identity/domain/context.py` 中 `select_membership` 用 `break` 而非 `continue` 的 bug
- 修复 `files/domain/multipart.py` 中 `delete_batch` 的 nil UUID 逻辑不严谨问题
- 修复 `common/redis.py` 多余的 `cast` 调用
- 修复 `governance/domain/scanner.py` 缺少泛型类型参数
- 修复 `identity/infrastructure/repositories.py` 第 89 行缺少返回类型注解
- 修复 `governance/domain/access_review.py` 未使用的 `uuid4` 导入
- 运行全量 ruff + mypy 零错误，全量测试通过

## Capabilities

### Modified Capabilities
- `backend-api-contract`: 契约校验增加反向检查
- `backend-identity-authorization`: 修复多 membership 选择逻辑；修复类型注解

### New Capabilities
无；本 change 仅修复已实现能力的 bug。

## Impact

- 修改 `migrations/env.py`、`scripts/check_openapi.py`、`identity/domain/context.py`、`files/domain/multipart.py`、`common/redis.py`、`governance/domain/scanner.py`、`identity/infrastructure/repositories.py`、`governance/domain/access_review.py`
- 不新增 API 端点、数据库表或外部依赖
- 不影响前端契约