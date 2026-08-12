## Context

本 change 修复 2026-08-11 explore 排查发现的 8 个 bug，均为小范围修改，不涉及架构变更。

## Decisions

### 1. 修复分类

所有修复按影响范围分为三类：

**类型安全修复（低风险）：**
- `scanner.py`：`list[dict]` → `list[dict[str, object]]`
- `repositories.py`：`find_by_normalized_email` 添加 `-> PasswordCredential | None`
- `access_review.py`：移除未使用的 `uuid4` 导入
- `redis.py`：移除多余的 `cast(Redis, ...)`

**逻辑修复（中风险）：**
- `select_membership`：`break` → `continue`，确保遍历所有 membership
- `delete_batch`：调用方传入 `tenant_id`/`principal_id` 而非使用 nil UUID
- `check_openapi.py`：增加基线→运行时反向检查

**基础设施修复（低风险）：**
- `env.py`：添加 `access_review_models` 导入

### 2. 修复策略

每类修复独立提交，按风险从低到高执行。每完成一类运行全量 ruff + mypy + pytest 验证。

### 3. 不修改的内容

- 不新增或修改数据库迁移
- 不修改 API 端点签名
- 不修改前端契约