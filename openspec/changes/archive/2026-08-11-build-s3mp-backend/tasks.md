## 1. 契约基线

- [x] 1.1 创建 `contracts/openapi.yaml`、API 通用约定、稳定错误码和权限操作目录
- [x] 1.2 定义 `/api/v1/me`、用户、用户组、角色、RoleBinding、有效权限和授权模拟契约
- [x] 1.3 定义应用、API Key、存储空间、文件、上传、multipart、配额和审计契约
- [x] 1.4 提供成功、空状态、拒绝、冲突、过期和部分失败的契约示例
- [x] 1.5 建立运行时 OpenAPI、契约基线、错误码和权限目录的 CI 校验

## 2. 后端工程骨架

- [x] 2.1 在独立后端仓库根目录创建 Python 3.12、uv 和 `src/s3mp` layout 工程
- [x] 2.2 配置 FastAPI、Pydantic、SQLAlchemy 2、Alembic、PostgreSQL 和 Redis
- [x] 2.3 建立 common、identity、tenant、authorization、applications、files、storage、audit、governance 模块
- [x] 2.4 配置格式化、类型检查、pytest、迁移测试和 CI 命令
- [x] 2.5 实现配置、外部秘密引用、健康检查、request ID、稳定错误和日志脱敏基础
- [x] 2.6 创建 `deploy/**` 本地运行及环境配置模板

## 3. 租户、用户与认证

- [x] 3.1 建立 tenant、principal、user、external_identity、membership、状态历史和 session 模型
- [x] 3.2 添加租户组合唯一约束、外键和 repository tenant 强制过滤
- [x] 3.3 实现本地密码认证、HttpOnly 会话、CSRF、登录限流和会话撤销
- [x] 3.4 实现 PrincipalContext、租户选择和 `/api/v1/me`
- [x] 3.5 定义 AuthProvider/OIDC Provider 接口和 issuer+subject 映射占位
- [x] 3.6 测试跨租户 ID 替换、成员状态、禁用用户和会话失效

## 4. 用户组、角色和授权

- [x] 4.1 建立 group、group_member、permission、role、role_permission 和 scoped role_binding 模型
- [x] 4.2 实现用户、成员、用户组、角色和 RoleBinding 管理 API
- [x] 4.3 实现 canonical prefix、父级继承、多 allow 合并、deny 优先和 default deny
- [x] 4.4 实现 authorization version 推进及缓存、会话、cursor 和任务重验
- [x] 4.5 实现直接授权原因/有效期、委派子集和职责分离校验
- [x] 4.6 实现有效权限查询和授权模拟，返回稳定原因及来源
- [x] 4.7 测试组继承、调组、授权到期、停用回收、委派越界和平台管理员无隐式数据读取权

## 5. 应用与 API Key

- [x] 5.1 建立 application、application_owner 和 api_key 模型
- [x] 5.2 实现 key ID、高熵 secret、pepper 摘要和一次展示
- [x] 5.3 实现 Key 到期、轮换、重叠窗口、禁用和吊销
- [x] 5.4 实现 `S3MP-Key` 认证及 Key、应用、租户限流
- [x] 5.5 实现 Key scope、应用 RoleBinding、目录策略和治理规则的权限交集
- [x] 5.6 实现孤儿应用检测和 Owner 接管流程
- [x] 5.7 测试跨租户 Key、scope 降权、限流、吊销及敏感日志

## 6. S3 连接与目录安全

- [x] 6.1 验收 Region、TLS/网关、预签名上限、网络和 CORS 条件
- [x] 6.2 实现显式 endpoint、region、SigV4、path-style 的 S3 Adapter
- [x] 6.3 建立 storage_connection、storage_space、Bucket/root prefix 映射和 capability flags
- [x] 6.4 实现非破坏性读探测和测试前缀写读删验收
- [x] 6.5 实现 canonical object key 验证和不可变 AuthorizedCommand
- [x] 6.6 实现 S3 操作 allowlist、稳定错误和连接级兼容开关
- [x] 6.7 测试编码绕过、相似前缀、Content-Length、Content-Type、ETag 非 MD5 和 workaround

## 7. 文件与预签名

- [x] 7.1 建立 file_object、upload_session 和安全 cursor 模型
- [x] 7.2 实现授权范围内对象列举和 HeadObject 元数据
- [x] 7.3 实现小文件代理上传、准确 Content-Length、MIME、配额和覆盖语义
- [x] 7.4 实现短时 PUT 预签名、pending 状态、完成确认和实际对象校验
- [x] 7.5 实现短时 GET 预签名、TTL 上限和 URL 指纹审计
- [x] 7.6 实现按连接 capability 选择直传或代理回退
- [x] 7.7 测试方法、签名头、key、TTL 和停用主体不可新签发

## 8. Multipart 与对象状态机

- [x] 8.1 建立 multipart session/part 和租户、主体、对象、配额绑定
- [x] 8.2 实现创建、分片、列举、完成校验和 Abort API
- [x] 8.3 实现过期 multipart 与 pending 对象的幂等清理 Worker
- [x] 8.4 建立 copy/move/delete operation record 和部分失败恢复
- [x] 8.5 实现批量删除固定范围、二次确认和幂等执行
- [x] 8.6 测试跨会话 upload ID、过期清理、移动删源失败和范围变化

## 9. 配额、审计与访问审查

- [x] 9.1 建立 quota、quota_reservation、预留、结算、释放和周期对账
- [x] 9.2 建立不可经业务 API 修改的 tenant-scoped audit_event
- [x] 9.3 建立 access_review、review_item 和 approval_request
- [x] 9.4 扫描无期限直接授权、长期未使用授权、孤儿应用和残留绑定
- [x] 9.5 实现高风险操作审计失败关闭和安全监控告警
- [x] 9.6 验证敏感数据不进入日志、审计、追踪和指标

## 10. 后端验收

- [x] 10.1 验证契约、迁移、单元、集成和安全测试全部通过
- [x] 10.2 打通登录到用户停用回收的权限治理纵向流程
- [x] 10.3 在测试 Bucket 验收读写、预签名、multipart、复制和删除
- [x] 10.4 执行多租户 IDOR、目录绕过、委派、API Key 和故障演练
- [x] 10.5 输出契约版本、前端同步说明、部署和回滚手册
