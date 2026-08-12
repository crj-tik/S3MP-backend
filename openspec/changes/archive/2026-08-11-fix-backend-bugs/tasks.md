## 1. 类型安全修复

- [x] 1.1 修复 `governance/domain/scanner.py` 泛型类型参数：`list[dict]` → `list[dict[str, object]]`
- [x] 1.2 修复 `identity/infrastructure/repositories.py` 第 89 行缺少返回类型注解 `-> PasswordCredential | None`
- [x] 1.3 修复 `governance/domain/access_review.py` 移除未使用的 `uuid4` 导入
- [x] 1.4 修复 `common/redis.py` 移除多余的 `cast(Redis, ...)` 调用

## 2. 逻辑修复

- [x] 2.1 修复 `identity/domain/context.py` 中 `select_membership` 的 `break` → `continue`
- [x] 2.2 修复 `files/domain/multipart.py` 中 `delete_batch` 的 nil UUID 问题
- [x] 2.3 修复 `scripts/check_openapi.py` 增加基线→运行时的反向检查

## 3. 基础设施修复

- [x] 3.1 修复 `migrations/env.py` 添加 `access_review_models` 导入

## 4. 验证

- [x] 4.1 运行 `ruff check` 零错误（源码零错误，测试文件预存 E501/S105 不在修复范围）
- [x] 4.2 运行 `mypy` 零错误
- [x] 4.3 运行 `pytest` 176 个测试全部通过（含新增的 select_membership 多 membership 测试）