# 平台控制面上线与回滚证据

## 上线顺序

1. 以部署身份执行 `alembic upgrade head`，确认版本为 `0020_support_access`。
2. 设置精确 `S3MP_BROWSER_ORIGINS` 与生产秘密文件引用；生产环境不得配置
   `S3MP_BROWSER_COOKIE_SECURE=false` 或通配符 Origin。
3. 在受控终端执行 `scripts/bootstrap_platform_admin.py` 创建首个管理员。
4. 前端先登录账户、选择活跃租户，再调用租户数据 API；平台运维使用独立
   `/api/v1/platform/*` API。
5. 将支持人员访问限定为申请、不同人员审批、有限期与审计的 support-access 流程。
6. 在平台调度器中至少每分钟运行 `scripts/expire_support_access.py`，以物化到期撤销记录并撤销
   可能仍存的租户会话。

## 本地验证证据

- Alembic 当前 head：`0020_support_access`。
- 应用 lifecycle readiness：PostgreSQL、Redis、MinIO 均返回 `ok`。
- 全量测试：`324 passed`。
- Ruff format/check、Mypy、OpenAPI runtime 对照（80 operations）、合约目录校验均通过。

## 回滚

控制面迁移只增加表、列与索引。紧急回滚应先停止暴露账户与平台路由，撤销受影响账户/租户
会话及 support-access，再回退应用版本。不要把平台角色写入租户 RoleBinding，也不要绕开
到期回收；保留审计与新增表用于取证。数据库结构仅在确认没有依赖的会话或访问记录后，才考虑
执行受控的 Alembic downgrade。
