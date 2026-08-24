## Context

现有应用数据面将 API Key 所属应用同时视为目录所有者和授权主体，且近期尝试将 `application_code` 用于目标目录寻址。该语义无法表示“应用 A 持有应用 B 的 Key 并操作 B 的目录”这一场景，也无法清晰审计操作来源。

## Goals / Non-Goals

**Goals:**

- 明确目标资源与审计操作主体的两种应用身份。
- 支持同租户应用协作，同时保持 API Key 不暴露内部应用 ID。
- 使浏览器与应用 API 使用各自稳定且清晰的寻址方式。
- 让异步上传、multipart 和对象操作在后续执行时保留完整审计归属。

**Non-Goals:**

- 不引入跨租户共享。
- 不新增应用间目录白名单；持有目标应用有效 Key 即为访问目标目录的凭据。
- 不改变物理对象 key 的 `tenant/application_id` 命名空间格式。

## Decisions

### API Key selects the target application

应用 API 请求认证后，以 Key 绑定的 `application_id` 解析目标 storage space 和 namespace。请求体或路径的 `application_code` 不参与目标目录选择。

替代方案是让 code 选择目标目录并验证 Key 所属应用等于 code。该方案无法支持用户确认的跨应用 Key 持有场景，故不采用。

### Request code is an auditable actor application

应用 API 所有创建、读取和变更数据面入口统一要求 `application_code`。服务端按 API Key tenant 查 active 应用，得到 `actor_application_id`；找不到或跨租户时以不泄露存在性的失败响应结束。

审计、文件操作、上传会话和 multipart 会话保存目标应用与操作应用两组归属。重试、完成、取消和异步 worker 使用保存的 actor 状态进行复核。

### Browser routes remain application-ID routes

浏览器路由保留 `/applications/{application_id}/...`，仅接受人类会话，目标空间由该 ID 解析。审计主体来自会话 principal，不接受 application_code 作为替代主体。

### API contract separates route families

应用 API 使用稳定的应用数据面路由并要求 `application_code` 参数；浏览器管理路由保留应用 ID。对于同一资源动作，契约和 OpenAPI 文档明确标注调用方类型、目标解析来源与审计主体，防止前端误用应用 API 入口。

## Risks / Trade-offs

- [目标应用 Key 泄露即允许同租户任意应用 code 声称操作] → Key scope、轮换、吊销和审计保留；code 仅可标识 active 同租户应用，不能提升 Key scope。
- [操作应用删除后异步操作归属难以复核] → 异步任务保存 actor/target 标识和状态版本，执行前复核；失效则取消或失败。
- [双路由产生客户端混淆] → OpenAPI 分组、前端封装分离和契约测试禁止浏览器使用应用 API 路由。

## Migration Plan

1. 撤回当前“仅凭 Key 自动定位目录”临时入口及 code 作为目标目录的改动。
2. 迁移审计与长生命周期会话字段，回填既有记录的目标应用；历史记录的操作应用保留为空或标为未知历史来源。
3. 发布新的应用 API 与浏览器 API 契约，更新前端和调用示例。
4. 部署后验证同租户跨应用操作、跨租户 code 拒绝、浏览器应用 ID 操作与审计完整性。
