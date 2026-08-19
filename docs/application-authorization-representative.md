# 应用授权代表接口

应用仍使用自己的 API Key 和 application principal 请求文件数据面。平台在当前租户内解析应用唯一的授权代表 Membership，并将该成员的直接角色和用户组角色作为权限来源；不会跨租户读取同一用户的角色，也不会把应用伪装成用户。

## 创建应用

`POST /api/v1/applications`

```json
{
  "name": "image-worker",
  "authorization_membership_id": "<membership-uuid>"
}
```

省略 `authorization_membership_id` 时，服务端使用当前登录成员；显式指定时必须属于当前租户且为 active。

## 查询、绑定或替换授权代表

- `GET /api/v1/applications/{application_id}/authorization-representative`
- `PUT /api/v1/applications/{application_id}/authorization-representative`
- `DELETE /api/v1/applications/{application_id}/authorization-representative`

绑定请求（可带当前应用授权版本，避免并发覆盖）：

```json
{
  "membership_id": "<membership-uuid>",
  "expected_application_version": 3
}
```

PUT 是同一应用的幂等替换操作；DELETE 会撤销代表并递增应用 `authorization_version`。应用 API Key 不得调用这些管理端点。

## 授权计算

文件操作必须同时满足：API Key scope、授权代表直接/用户组 RoleBinding、storage space/canonical prefix、租户治理和操作白名单。任一 deny 优先；授权代表失效后，新的请求和排队任务都会被拒绝。绑定、替换、撤销和文件授权证据写入租户审计，且不记录 secret。
