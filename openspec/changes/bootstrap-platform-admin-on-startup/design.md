## Context

平台管理员 bootstrap 已有 `PlatformBootstrapStateModel` 和 `create_initial_platform_admin`，但交互式脚本无法用于容器启动，且管理员被清理后单例状态会阻止开发环境重新引导。

## Design

- 新增非交互式 `scripts.ensure_platform_admin`，读取 `S3MP_BOOTSTRAP_ADMIN_*` 配置，不打印密码。
- 新增容器 entrypoint，在启动主进程前执行一次引导；所有运行角色可安全并发调用同一幂等逻辑。
- 仓储方法先在事务锁内检查活跃管理员；已有管理员直接返回；无管理员时复用/创建单例状态并创建账户、角色绑定和审计事件。
- Compose 只提供配置映射，自动引导默认关闭；开发环境通过 `deploy/.env` 显式开启。生产校验拒绝启用开发密码引导。
- 密码仅保存为现有 `PasswordHasher` 生成的 scrypt 哈希，环境变量不写入日志或响应。

## Failure Handling

- 配置不完整时启动引导失败并返回非零状态，避免容器以“看似可用但无管理员”的状态运行。
- 已有管理员时重复执行是成功操作。
- 事务失败自动回滚，不留下半个账户或孤立角色绑定。
