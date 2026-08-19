## Why

当前共享 Bucket 容量和配额 API 使用字节数作为外部输入，管理员和前端必须手工换算大整数，容易产生误填和单位误解。需要将外部管理单位统一为 GiB，同时保留后端内部字节账本，避免容量计算损失精度。

## What Changes

- **BREAKING** 将 Bucket 容量配置从 `S3MP_S3_BUCKET_CAPACITY_BYTES` 改为 `S3MP_S3_BUCKET_CAPACITY_GIB`。
- **BREAKING** 将平台配额创建、修改请求中的 `limit_bytes` 改为 `limit_gib`。
- 配额响应、列表和共享池统计增加面向客户端的 GiB 字段，前端不再自行处理字节换算。
- 内部数据库字段和所有并发、预留、结算、对账计算继续使用整数 bytes。
- 对 GiB 输入执行非负、整数和 Bucket/租户/应用边界校验，并统一返回稳定错误。
- 更新 OpenAPI、元数据、部署文档、前端契约校验和测试；不兼容的旧字节字段从公开契约移除。

## Capabilities

### New Capabilities

- `quota-external-unit-contract`: 定义配额管理 API 和部署配置的 GiB 外部单位，以及与内部 bytes 账本的转换边界。

### Modified Capabilities

- `application-storage-quotas`: 配额输入输出由 bytes 外部单位改为 GiB，同时保持内部精确容量账本和边界校验。
- `shared-s3-application-storage`: 共享 Bucket 容量配置改用 GiB，并在配额分配时转换为精确 bytes 上限。

## Impact

- 影响 `src/s3mp/common/config.py`、配额平台路由/服务/仓储、OpenAPI 契约、metadata catalog 和部署 `.env` 文档。
- 影响前端创建/修改配额及容量展示的请求字段和响应字段。
- 不改变 PostgreSQL 配额表的内部 byte 字段，不需要重算已存储文件大小。
- 这是公开 API 的破坏性单位调整，部署时必须同步更新后端环境变量和前端契约。
