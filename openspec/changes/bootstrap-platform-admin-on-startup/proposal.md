## Why

本地开发数据库被清理或首次初始化后，平台没有可登录的内置管理员，容器虽能启动但无法完成平台管理联调。需要一个幂等、并发安全且默认关闭的启动引导机制。

## What Changes

- 容器启动时可显式开启平台管理员引导检查。
- 数据库没有活跃 `platform_admin` 时，使用配置的开发账号信息创建管理员并授予内置角色。
- 已存在活跃管理员时不重复创建、不修改密码。
- 保留现有交互式 bootstrap 脚本，并让数据库单例锁支持管理员恢复场景。
- 生产环境默认关闭自动引导，禁止把开发默认密码带入生产。

## Capabilities

### New Capabilities

- `platform-admin-startup-bootstrap`: 启动期幂等检查与受控创建平台管理员。

### Modified Capabilities

- 无。

## Impact

- 影响平台仓储 bootstrap 逻辑、容器 entrypoint、Compose 环境变量和启动脚本。
- 不新增公开 HTTP 接口，不改变租户或用户登录契约。
- 需要增加启动脚本和并发/重复启动测试。
