# 浏览器真实模式接入

前端与后端通过 Cookie 传递会话，所有请求必须使用 `credentials: "include"`。
会话令牌不会出现在 JSON 响应、LocalStorage 或前端日志中。

## 本地开发

推荐 Vite 将 `/api` 反向代理到后端，以避免跨域 Cookie 调试复杂度：

```ts
server: {
  proxy: { "/api": "http://localhost:8000" },
}
```

若前端直连后端，则设置后端 `S3MP_BROWSER_ORIGINS=http://localhost:5173`；不要使用
`*`。本地 HTTP 开发还须显式设置 `S3MP_BROWSER_COOKIE_SECURE=false`，生产环境不允许此设置。

## 登录与租户选择

1. `POST /api/v1/auth/login`，提交邮箱和密码。后端写入 HttpOnly
   `s3mp_account_session` 与可读取的 `s3mp_account_csrf` Cookie，并返回账户和可选租户摘要。
2. 前端从 Cookie 读取 CSRF 值，放入 `X-S3MP-CSRF` 请求头。
3. `POST /api/v1/auth/tenant-sessions`，传入 `tenant_id`。仅活跃且未过期的 Membership
   能得到独立的 `s3mp_session` 与 `s3mp_csrf` Cookie。
4. 租户管理和文件 API 只接受 `s3mp_session`；账户会话本身不能访问它们。
5. 切换租户时再次调用 tenant-sessions。退出账户使用 `POST /api/v1/auth/logout`。

所有 Cookie 身份的 `POST`、`PUT`、`PATCH`、`DELETE`（登录除外）均须携带匹配的
CSRF Header；API Key 请求不使用此机制。

## 平台运维

首次管理员只能由受控终端执行，部署完成迁移后运行：

```powershell
.venv\Scripts\python.exe scripts\bootstrap_platform_admin.py --email admin@example.com --display-name Admin
```

命令会交互式读取密码，不输出密码或会话令牌。平台 API 位于 `/api/v1/platform/*`，需要
账户会话加相应平台权限。平台管理员不是租户管理员：若需要帮助某个租户，必须走带理由、
双人审批和到期时间的 support-access 流程；该流程默认不授予文件内容权限。

## 生产部署

- `S3MP_ENVIRONMENT=production` 时，数据库、Redis、S3 与 Pepper 必须使用 `*_FILE` 秘密引用。
- `S3MP_BROWSER_ORIGINS` 仅列出精确 HTTPS 前端 Origin；带凭据 CORS 禁止通配符。
- Cookie 始终为 `Secure; HttpOnly; SameSite=Lax`（CSRF Cookie 例外：必须由前端读取）。
- 先运行 Alembic 迁移和 bootstrap，再暴露平台管理入口；回滚时先禁用这些入口并撤销受影响会话，
  不将平台角色转换成任何隐式租户授权。
