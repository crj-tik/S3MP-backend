## Purpose

为平台管理员和前端提供清晰一致的 GiB 配额输入输出，同时让后端继续用整数 bytes 进行精确的容量、并发预留和对账计算。

## ADDED Requirements

### Requirement: GiB is the public quota unit

所有平台配额管理请求和共享 Bucket 容量配置 SHALL 使用 GiB；配额响应 SHALL 提供对应的 GiB 展示字段。公开契约不得要求调用方提交或计算 `limit_bytes`。

#### Scenario: Create tenant quota in GiB

- **WHEN** 平台管理员提交 `limit_gib` 创建租户总配额
- **THEN** 系统 SHALL 按 `limit_gib × 1024³` 转换为内部 bytes，并返回 GiB 与内部一致的统计结果

#### Scenario: Reject invalid GiB input

- **WHEN** 请求提交负数、非整数、非有限值或未知配额单位
- **THEN** 系统 SHALL 返回稳定的 `422 validation_failed`，且不得写入配额

### Requirement: Exact internal conversion

系统 SHALL 只在 API/config 边界执行 GiB 到 bytes 的一次精确转换，内部账本、数据库字段、锁、预留、结算和对账 SHALL 使用整数 bytes。GiB 展示值 SHALL 由内部 bytes 经过确定性转换生成。

#### Scenario: Capacity boundary is exact

- **WHEN** Bucket 容量和租户配额均以整数 GiB 配置且租户配额等于 Bucket 容量
- **THEN** 系统 SHALL 接受该配置；超过一个 GiB SHALL 被拒绝，不得因浮点舍入放行

#### Scenario: Existing usage is displayed in GiB

- **WHEN** 已有文件使用量或预留量不是 GiB 的整数倍
- **THEN** 系统 SHALL 返回明确的非整数 GiB 展示值，同时内部 bytes 值保持精确且不被四舍五入后回写

### Requirement: Contract and deployment consistency

OpenAPI、metadata catalog、部署示例和服务运行时 SHALL 发布同一组 GiB 字段和配置名称；旧的 bytes 外部字段 SHALL 被标记为移除，不得只在文档中保留模糊别名。

#### Scenario: Frontend reads quota contract

- **WHEN** 前端读取 OpenAPI 或 metadata catalog
- **THEN** 它 SHALL 能发现 `limit_gib`、GiB 统计字段和 GiB 配置说明，不需要手写 bytes 换算规则

#### Scenario: Deployment starts without capacity

- **WHEN** 已配置共享 S3 但未配置 Bucket GiB 容量
- **THEN** 服务 SHALL 明确记录配置错误或警告，且不得把未限制容量误报为有限配额
