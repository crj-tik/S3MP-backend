## Context

当前配额数据库和上传账本已经以整数 bytes 保存 limit、used、reserved。需要只改变公开配置/API 的输入输出单位，避免迁移历史文件和重写账本。

## Goals / Non-Goals

**Goals:**

- 让管理员和前端只处理 GiB。
- 在配置、路由、服务、仓储、OpenAPI 和 metadata catalog 中保持同一命名和单位。
- 保证 GiB 到 bytes 的转换确定、非负、无浮点误差，并继续执行现有配额边界。

**Non-Goals:**

- 不修改 PostgreSQL 内部 byte 字段。
- 不迁移或重算已有文件、预留和对账记录。
- 不改变共享 Bucket、租户、应用命名空间和权限模型。

## Decisions

### 1. 采用 GiB 而非十进制 GB

对外使用整数 GiB，换算常量固定为 `1024 ** 3`。GiB 与当前二进制容量账本一致；十进制 GB 会让磁盘容量显示和数据库 byte 边界产生歧义。

### 2. 外部字段使用 `*_gib`，内部字段继续使用 `*_bytes`

路由请求使用 `limit_gib`，配置使用 `S3MP_S3_BUCKET_CAPACITY_GIB`，响应提供 GiB 展示字段。服务层立即转换为 bytes，后续领域、仓储、锁和对账代码不接触外部单位。

### 3. 破坏性移除旧 bytes 输入

不接受 `limit_bytes` 或 `S3MP_S3_BUCKET_CAPACITY_BYTES` 作为公开兼容别名，避免同一个值在不同客户端中被解释成两种单位。部署文档明确要求先替换环境变量，再滚动重启服务。

### 4. 展示值允许小数但不回写

内部 bytes 不是 GiB 整数倍时，响应中的 GiB 展示字段使用稳定的小数格式；任何修改请求仍要求整数 GiB，修改只按整数 GiB 转换后校验和持久化。

## Risks / Trade-offs

- [前端未同步会收到 422] → 先发布契约并同步前端请求字段，再部署后端；旧字段不做静默兼容。
- [容量配置遗漏导致无 Bucket ceiling] → 启动时将 GiB 配置缺失提升为明确的生产配置错误；开发环境可保留警告但不能声称有上限。
- [非整数 GiB 使用量显示复杂] → 同时提供稳定的 GiB 展示精度和内部精确 bytes 诊断字段，禁止把展示值反向写回。

## Migration Plan

1. 将现有 `S3MP_S3_BUCKET_CAPACITY_BYTES` 换算为 GiB，写入 `S3MP_S3_BUCKET_CAPACITY_GIB`。
2. 先更新 OpenAPI、metadata catalog 和前端调用，再部署后端。
3. 重启 API、Worker、Scheduler，确认配置日志和 readiness。
4. 执行配额边界、上传预留、契约和容器测试。
5. 回滚时恢复旧版本与旧配置文件；数据库 byte 账本无需回滚或迁移。

## Open Questions

无。公开单位固定为整数 GiB。
