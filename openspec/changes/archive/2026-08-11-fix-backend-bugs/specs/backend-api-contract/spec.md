## MODIFIED Requirements

### Requirement: 契约一致性
系统 SHALL 自动比较运行时 OpenAPI 与 `contracts/openapi.yaml`，SHALL 双向检查（运行时比基线多报错，基线比运行时多也报错），并 SHALL 为契约示例和权限目录提供校验。

#### Scenario: 实现与契约不一致（运行时缺少基线端点）
- **WHEN** CI 检测到基线定义了端点但运行时未实现
- **THEN** 系统 SHALL 使检查失败并阻止无审阅的漂移

#### Scenario: 实现与契约不一致（运行时多出基线端点）
- **WHEN** CI 检测到运行时 Schema、路径或响应与契约基线不一致
- **THEN** 系统 SHALL 使检查失败并阻止无审阅的漂移