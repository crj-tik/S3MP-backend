## Why

公开平台账户注册接口 `/api/v1/account/register` 已被认证中间件视为公开路径，前端也按“注册无需已有会话 CSRF 凭证”实现。但后端浏览器 CSRF 中间件只豁免登录路径；当浏览器残留账户或租户会话 Cookie 时，注册请求会被错误拒绝，导致真实联调出现 `csrf_validation_failed`。

## What Changes

- 将 `/api/v1/account/register` 纳入后端浏览器 CSRF 的公开豁免路径。
- 保持登录、登出、租户切换及平台/租户业务变更的现有 CSRF 保护不变。
- 增加带已有账户会话、带已有租户会话以及无会话三种注册请求的 HTTP 回归测试。
- 在认证能力规格中明确：公开注册不要求已有 CSRF Cookie；有会话的浏览器访问注册也不能因为残留会话被 CSRF 中间件误拦截。

## Capabilities

### New Capabilities

无。本变更修复既有浏览器账户认证能力，不引入新的公开能力。

### Modified Capabilities

- `browser-account-authentication`: 明确公开账户注册路径的 CSRF 豁免边界，并保持所有已认证 unsafe 请求的 CSRF 校验。

## Impact

- 后端：`src/s3mp/common/browser_security.py` 及浏览器账户 HTTP 测试。
- 契约/文档：补充注册接口免 CSRF 的说明，避免前端为注册请求注入不存在的 token。
- 安全边界：仅放宽公开注册路径；不会放宽账户会话、租户会话或平台管理接口的 CSRF 校验。
