## ADDED Requirements

### Requirement: Startup bootstrap is explicitly enabled
容器 MUST 仅在 `S3MP_BOOTSTRAP_ADMIN_ENABLED=true` 且运行环境不是 production 时执行自动管理员引导；未开启或生产环境 MUST 跳过自动创建。

#### Scenario: Production is protected from development bootstrap
- **WHEN** `S3MP_ENVIRONMENT=production`
- **THEN** 启动流程不读取开发管理员密码，也不创建或修改平台账户

### Requirement: Missing administrator is created idempotently
启动引导 MUST 检查活跃、未撤销的 `platform_admin` 绑定；不存在时创建配置账号、密码哈希、角色绑定和审计记录。

#### Scenario: First startup creates the administrator
- **WHEN** 数据库没有活跃平台管理员且引导配置完整
- **THEN** 创建指定邮箱、工号、姓名的活跃账户并授予 `platform_admin`

#### Scenario: Repeated startup does not duplicate the administrator
- **WHEN** 已存在活跃平台管理员
- **THEN** 引导成功结束且不重复创建账户、不重置密码

### Requirement: Bootstrap is concurrency safe
管理员创建 MUST 使用数据库事务和现有单例/行锁，多个容器同时启动时最多创建一个管理员。

#### Scenario: API and worker start together
- **WHEN** 多个容器并发执行引导
- **THEN** 一个执行创建，其他执行检测到已存在管理员并正常退出
