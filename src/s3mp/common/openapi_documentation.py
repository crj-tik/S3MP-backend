"""Canonical Chinese documentation applied to the runtime OpenAPI schema."""

from __future__ import annotations

from typing import Any

OPERATION_DESCRIPTIONS: dict[str, str] = {
    "update_current_application_file_metadata": (
        "使用 record_etag 原子替换文件记录元数据，不修改对象内容或对象 ETag。"
    ),
    "live_health_live_get": "检查 API 进程是否存活；不检查数据库、Redis 或对象存储。",
    "ready_health_ready_get": "检查 API 是否已就绪，并验证已启用的外部依赖。",
    "get_metadata_catalog": "获取前端使用的状态、枚举、授权效果和状态流转目录。",
    "get_me": "获取当前已选租户中的身份、成员关系与有效权限上下文。",
    "list_users": "列出当前租户可见的用户账户。",
    "list_member_candidates": (
        "搜索尚未加入当前租户的全局已注册用户候选；支持邮箱、姓名和工号模糊查询。"
    ),
    "get_user": "获取当前租户中指定用户的公开身份信息。",
    "list_members": "列出当前租户的成员关系。",
    "create_member": "将已有用户加入当前租户，或创建受邀成员关系。",
    "get_member": "获取当前租户中指定成员关系的详情。",
    "update_member": "更新成员状态；暂停、移除或到期会立即回收租户权限。",
    "list_group_members": "列出指定用户组中的成员关系。",
    "add_group_member": "将当前租户成员加入指定用户组。",
    "remove_group_member": "将成员从指定用户组移除。",
    "get_permission_catalog": "获取当前租户可配置的权限目录；不包含任何 platform.* 平台权限。",
    "account_login": (
        "校验邮箱或公司系统号及密码并建立账户会话；响应设置账户会话 Cookie "
        "和可读的账户 CSRF Cookie，同时清除浏览器中已有的租户会话 Cookie；"
        "并返回当前账户真实的 platform_permissions；但不会自动选择租户。"
    ),
    "register_account": (
        "注册全局平台账户；仅创建账户身份，不创建租户成员关系或平台角色；"
        "该公开接口不要求已有会话或 X-S3MP-CSRF 请求头。"
    ),
    "get_account_context": "获取当前账户及其可选择的活跃租户摘要。",
    "accept_tenant_invitation": (
        "接受当前账户的租户邀请并将成员关系从 invited 转为 active；客户端必须把 "
        "s3mp_account_csrf Cookie 的值原样放入 X-S3MP-CSRF 请求头。"
    ),
    "account_logout": (
        "撤销当前账户会话及该账户的租户会话，并清除账户与租户 Cookie；浏览器随后跟随 302 到"
        "配置的 CAS 全局登出地址。客户端必须以携带 csrf_token 的原生表单提交该请求。"
    ),
    "select_tenant_session": (
        "为账户选择一个活跃租户成员关系，并建立独立的租户会话；客户端必须把 "
        "s3mp_account_csrf Cookie 的值原样放入 X-S3MP-CSRF 请求头。"
    ),
    "list_platform_tenants": "列出平台可管理的租户生命周期摘要；不返回租户数据面内容。",
    "create_platform_tenant": "创建租户，并在同一事务中建立指定初始管理员的成员关系和管理员授权。",
    "get_platform_tenant": "获取平台视角下的租户生命周期摘要。",
    "update_platform_tenant": "更新租户名称或生命周期状态。",
    "grant_platform_role": "为一个全局账户创建或替换平台角色集合；一个用户仅保留一项有效授权。",
    "update_platform_role_assignment": "修改指定全局账户的整个平台角色集合和统一有效期。",
    "revoke_platform_role": "撤销指定全局账户的全部有效平台角色。",
    "request_support_access": "提交针对指定租户的限时支持访问申请；默认不包含文件内容权限。",
    "approve_support_access": "由不同的平台人员批准支持访问申请，并物化限时租户授权。",
    "revoke_support_access": "撤销已申请或已批准的支持访问，并回收其有效租户会话。",
    "list_platform_accounts": "分页列出平台账户目录，可按邮箱、系统号、姓名和账户状态筛选。",
    "get_platform_account": "获取平台账户的安全摘要；不返回密码、会话或密钥信息。",
    "reset_platform_account_password": "重置指定活跃平台账户的密码，并撤销其全部账户和租户会话。",
    "import_platform_accounts": "按 Excel 批量创建平台账户；已占用身份和无效行不会覆盖已有账户。",
    "list_platform_roles": "列出平台角色及其平台权限目录。",
    "list_platform_role_bindings": "按用户分页列出有效的平台角色授权集合；每个用户仅返回一项。",
    "list_support_access": "分页列出支持访问申请及其待审批、已批准、已撤销或已过期状态。",
    "get_support_access": "获取单条支持访问申请的安全详情和授权物化记录。",
    "list_platform_audit_events": "分页检索平台控制面审计事件，可按动作、资源类型和资源标识筛选。",
    "get_platform_audit_event": "获取单条平台审计事件的脱敏详情。",
    "list_groups": "列出当前租户的用户组。",
    "create_group": "创建当前租户的用户组。",
    "get_group": "获取指定用户组详情。",
    "update_group": "更新指定用户组的名称或描述。",
    "delete_group": "删除指定用户组；存在依赖时会拒绝删除。",
    "list_roles": "列出当前租户的角色及其权限。",
    "create_role": "创建当前租户的自定义角色。",
    "get_role": "获取指定角色及其权限详情。",
    "update_role": "更新自定义角色；系统内置角色不可通过此接口修改。",
    "list_role_bindings": "列出当前租户的成员或用户组角色绑定，可按主体筛选。",
    "create_role_binding": "在调用者可委派的权限范围内创建成员或用户组角色绑定。",
    "update_role_binding": "修改指定成员或用户组的现有角色绑定；同一主体可绑定多个不同角色。",
    "get_role_binding": "获取指定角色绑定及其有效期。",
    "revoke_role_binding": "撤销指定角色绑定并使相关授权立即失效。",
    "get_effective_permissions": "解释指定主体在当前租户内的有效角色权限来源。",
    "simulate_authorization": "在不改变授权状态的前提下模拟一次访问决策。",
    "list_applications": "列出当前租户的应用及其所有者状态。",
    "create_application": "创建应用、生成其固定存储目录，并绑定一个租户成员作为初始授权代表。",
    "get_application": "获取指定应用的元数据与状态。",
    "get_application_authorization_representative": "获取应用当前绑定的租户成员授权代表。",
    "bind_application_authorization_representative": "为应用绑定一个同租户的活跃成员作为授权代表。",
    "revoke_application_authorization_representative": (
        "撤销应用当前绑定的成员授权代表并使其授权立即失效。"
    ),
    "update_application": "更新指定应用的名称或状态。",
    "takeover_application": "接管失去活跃所有者、处于待接管状态的应用。",
    "list_api_keys": "列出指定应用的 API Key 元数据；不会返回密钥明文。",
    "create_api_key": "为指定应用签发 API Key；密钥明文仅在本次响应中返回。",
    "get_api_key": "获取 API Key 的非敏感元数据。",
    "get_api_key_secret": "历史兼容接口，始终拒绝返回 API Key 密钥明文。",
    "rotate_api_key": "轮换 API Key，并按请求指定的重叠期保留旧 Key。",
    "revoke_api_key": "撤销 API Key 并返回剩余的已签发 URL 风险信息。",
    "list_storage_connections": "列出当前租户的对象存储连接摘要，不暴露连接凭据。",
    "get_storage_connection": "获取对象存储连接的脱敏配置和连通性状态。",
    "probe_storage_connection": "探测对象存储连接与其声明能力。",
    "list_files": "在当前应用的固定命名空间内列出文件对象。",
    "get_file": "获取指定文件对象的元数据；不直接返回对象存储凭据。",
    "delete_file": (
        "提交文件删除；file_ref 新轨无需 provider ETag，旧 UUID 轨继续按 If-Match 并发校验。"
    ),
    "restore_file": "在三个月保留期内恢复文件；仅租户管理主体可调用。",
    "create_file_operation": "创建文件复制、移动或其他受控异步操作。",
    "get_file_operation": "查询文件操作的状态、结果和可恢复错误。",
    "rename_current_application_file": (
        "异步重命名当前应用文件；必须提供当前 ETag 和幂等键。受理响应返回预创建目标"
        "文件的 ID、元数据、内容 ETag 与记录 ETag，但只有操作成功且文件状态为 "
        "available 后才可读取或下载。"
    ),
    "get_current_application_file_operation": "查询当前应用异步文件操作的状态和结果文件标识。",
    "create_direct_upload": "创建受授权、配额和幂等保护的直传会话，并返回短期 presigned PUT URL。",
    "get_direct_upload": "查询直传会话状态并重新签发仍有效的短期 PUT URL。",
    "complete_direct_upload": "服务端流式计算正文 SHA-256，校验直传对象并同步返回 file_ref。",
    "create_presigned_download": "为已授权的单个文件签发短期下载 URL。",
    "create_multipart_upload": "创建受配额和授权保护的分段上传会话。",
    "get_multipart_upload": "查询分段上传会话状态。",
    "abort_multipart_upload": "中止分段上传并释放相关保留资源。",
    "list_multipart_parts": "列出已确认的分段上传分片。",
    "upload_multipart_part": (
        "接收一个分片二进制并由服务端写入对象存储，同时保存 provider 返回的 ETag。"
    ),
    "complete_multipart_upload": (
        "合并分片后由服务端对完整对象流式计算 SHA-256，并同步返回 file_ref。"
    ),
    "list_quotas": "列出当前租户或应用的配额与使用量；历史空间记录仅作迁移兼容。",
    "get_quota": "获取指定配额的限制、已用量和预留量。",
    "update_quota": "更新配额上限；需要当前 ETag 以防并发覆盖。",
    "list_platform_quotas": "列出平台可管理的租户总配额和应用独立配额。",
    "create_platform_quota": "为租户配置总容量，或从租户容量中划分应用独立容量。",
    "update_platform_quota": "调整租户总配额或应用独立配额，并校验使用量和子配额边界。",
    "revoke_platform_quota": "撤销没有使用量和进行中预留的应用独立配额，使容量回到共享池。",
    "list_audit_events": "检索当前租户可见的脱敏审计事件。",
    "get_audit_event": "获取单条脱敏审计事件详情。",
}

OPERATION_PARAMETER_DESCRIPTIONS: dict[tuple[str, str], str] = {
    ("update_current_application_file_metadata", "application_code"): (
        "调用方应用代码，用于确认应用身份与审计归属。"
    ),
    ("update_current_application_file_metadata", "If-Match"): (
        "当前文件记录的 record_etag；用于拒绝覆盖较新的元数据。"
    ),
    ("update_current_application_file_metadata", "Idempotency-Key"): (
        "客户端生成的幂等键；相同业务动作重试时必须复用。"
    ),
}

OPERATION_SUMMARIES: dict[str, str] = {
    "update_current_application_file_metadata": "更新当前应用文件元数据",
}

FIELD_DESCRIPTIONS: dict[str, str] = {
    "id": "资源的服务端唯一标识。",
    "tenant_id": "租户的服务端唯一标识。",
    "user_id": "全局用户账户的服务端唯一标识。",
    "principal_id": "租户主体的服务端唯一标识。",
    "membership_id": "租户成员关系的服务端唯一标识。",
    "group_id": "用户组的服务端唯一标识。",
    "role_id": "角色的服务端唯一标识。",
    "role_binding_id": "角色绑定的服务端唯一标识。",
    "application_id": "应用的服务端唯一标识。",
    "api_key_id": "API Key 的服务端唯一标识。",
    "storage_space_id": "历史内部存储记录标识；仅用于迁移兼容，不是业务存储空间。",
    "connection_id": "存储连接的服务端唯一标识。",
    "file_id": "文件对象的服务端唯一标识。",
    "upload_id": "上传会话的服务端唯一标识。",
    "multipart_id": "分段上传会话的服务端唯一标识。",
    "operation_id": "异步文件操作的服务端唯一标识。",
    "quota_id": "配额记录的服务端唯一标识。",
    "audit_event_id": "审计事件的服务端唯一标识。",
    "request_id": "请求的服务端唯一标识，用于问题追踪。",
    "binding_id": "平台角色绑定的服务端唯一标识。",
    "cursor": "不透明分页游标；仅可用于相同查询条件的下一页请求。",
    "next_cursor": "下一页分页游标；无更多结果时为 null。",
    "limit": "本页最多返回的记录数。",
    "etag": "资源当前版本标识，用于并发控制。",
    "If-Match": "客户端已读取的资源 ETag；用于拒绝覆盖较新的服务端状态。",
    "Idempotency-Key": "客户端生成的幂等键；相同语义的重试会复用首次结果。",
    "X-S3MP-CSRF": (
        "浏览器会话的 CSRF 校验值；账户操作取自 s3mp_account_csrf Cookie，"
        "租户操作取自 s3mp_csrf Cookie，并原样放入此请求头。"
    ),
    "email": "用户登录邮箱地址。",
    "employee_number": "公司的唯一系统号或员工工号，用于账户识别和登录。",
    "identifier": "登录标识，可填写邮箱或公司的系统号、员工工号。",
    "password": "用户登录密码；仅用于本次认证，不会在响应中返回。",
    "display_name": "面向用户展示的名称。",
    "name": "资源名称，在所属租户范围内使用。",
    "description": "资源的可读说明。",
    "status": "资源当前生命周期状态。",
    "expires_at": "资源或授权的失效时间，采用 Asia/Shanghai（UTC+08:00）格式。",
    "created_at": "资源创建时间，采用 Asia/Shanghai（UTC+08:00）格式。",
    "updated_at": "资源最近更新时间，采用 Asia/Shanghai（UTC+08:00）格式。",
    "reason": "执行该敏感操作的业务原因。",
    "object_key": "应用存储命名空间内的规范相对对象路径。",
    "content_type": "对象的媒体类型。",
    "content_length": "对象实际内容长度，单位为字节。",
    "declared_size_bytes": "客户端声明的上传对象大小，单位为字节。",
    "part_number": "分段上传中从 1 开始的分片序号。",
    "permissions": "角色或主体拥有的权限名称集合。",
    "scopes": "API Key 被允许使用的权限范围集合。",
    "authorization_version": "授权状态版本；变化后旧会话和缓存会被重新验证。",
    "details": "非敏感的补充错误或结果信息。",
    "available_tenants": "当前账户可选择的活跃租户摘要列表。",
    "bucket": "对象存储服务中承载数据的存储桶名称。",
    "checksum": "服务端从最终对象正文计算的 SHA-256；客户端可不提交，完成响应会同步返回。",
    "file_ref": "S3MP 签发的确定性文件引用；新客户端用它进行增删改查，不需要保存 provider ETag。",
    "coarse_permissions": "用于快速判定的粗粒度有效权限名称集合。",
    "created_by": "创建该资源的主体标识。",
    "credential_reference": "服务端保存的存储凭据引用；不返回凭据明文。",
    "ctx": "认证或授权计算使用的上下文信息。",
    "current_tenant": "当前账户已选择的租户摘要；未选择时为 null。",
    "decision": "本次授权模拟得出的允许或拒绝决定。",
    "destination_key": "文件复制或移动操作的目标规范相对对象路径。",
    "detail": "面向调用方的错误或结果补充说明。",
    "mode": "上传会话模式；当前为 direct 或 multipart。",
    "method": "应用向短期上传 URL 发起请求时使用的 HTTP 方法。",
    "url": "由平台签发的短期上传 URL；仅用于当前上传会话，不应持久化。",
    "headers": "调用短期上传 URL 时必须携带的安全请求头集合。",
    "part_size": "建议的分片大小，单位为字节。",
    "effect": "角色绑定对权限产生的允许或拒绝效果。",
    "endpoint": "对象存储服务的访问端点地址。",
    "evaluated_at": "本次权限或状态计算完成的时间，采用 Asia/Shanghai（UTC+08:00）格式。",
    "initial_admin_user_id": "新租户的初始管理员全局用户账户标识。",
    "input": "用于授权模拟的输入条件。",
    "items": "当前页返回的资源记录列表。",
    "keys": "本次操作涉及的 API Key 或对象键摘要列表。",
    "limit_bytes": "可使用容量的最大字节数。",
    "limit_gib": "可使用容量的最大值，单位为 GiB；管理员配置时使用该字段。",
    "used_gib": "已确认使用量，单位为 GiB。",
    "reserved_gib": "进行中上传预留量，单位为 GiB。",
    "available_gib": "当前可继续预留的容量，单位为 GiB。",
    "allocated_gib": "该配额已用量与进行中预留量之和，单位为 GiB。",
    "allocation_mode": (
        "配额分配模式：tenant_total 租户总量，application_reserved 应用独立划分，"
        "storage_space_legacy 历史兼容模式。"
    ),
    "allocated_bytes": "该配额已用量与进行中预留量之和，单位为字节。",
    "tenant_limit_bytes": "租户总配额上限，单位为字节。",
    "tenant_used_bytes": "租户总配额已确认使用量，单位为字节。",
    "tenant_reserved_bytes": "租户总配额进行中预留量，单位为字节。",
    "tenant_available_bytes": "租户总配额当前可用量，单位为字节。",
    "allocated_application_limit_bytes": "所有活跃应用独立配额上限之和，单位为字节。",
    "allocated_application_used_bytes": "应用独立配额已确认使用量之和，单位为字节。",
    "allocated_application_reserved_bytes": "应用独立配额进行中预留量之和，单位为字节。",
    "shared_pool_limit_bytes": "未划分给应用独立配额的共享池上限，单位为字节。",
    "shared_pool_used_bytes": "共享池应用已确认使用量，单位为字节。",
    "shared_pool_reserved_bytes": "共享池应用进行中预留量，单位为字节。",
    "shared_pool_available_bytes": "共享池当前可继续预留的容量，单位为字节。",
    "tenant_limit_gib": "租户总配额上限，单位为 GiB。",
    "tenant_used_gib": "租户总配额已确认使用量，单位为 GiB。",
    "tenant_reserved_gib": "租户总配额进行中预留量，单位为 GiB。",
    "tenant_available_gib": "租户总配额当前可用量，单位为 GiB。",
    "allocated_application_limit_gib": "应用独立配额上限之和，单位为 GiB。",
    "allocated_application_used_gib": "应用独立配额已确认使用量之和，单位为 GiB。",
    "allocated_application_reserved_gib": "应用独立配额预留量之和，单位为 GiB。",
    "shared_pool_limit_gib": "共享池上限，单位为 GiB。",
    "shared_pool_used_gib": "共享池已确认使用量，单位为 GiB。",
    "shared_pool_reserved_gib": "共享池进行中预留量，单位为 GiB。",
    "shared_pool_available_gib": "共享池当前可用量，单位为 GiB。",
    "loc": "请求中发生校验问题的字段位置。",
    "member_count": "资源关联的有效成员数量。",
    "membership_status": "租户成员关系的当前状态。",
    "msg": "校验或错误信息的简要文本。",
    "operation_type": "异步文件操作的类型，例如复制或移动。",
    "overlap_seconds": "轮换 API Key 时旧 Key 仍可使用的重叠时长，单位为秒。",
    "parts": "已确认或待处理的分段上传分片列表。",
    "path_style": "是否使用路径风格的对象存储寻址方式。",
    "permission": "需要判定、授予或模拟的单个权限名称。",
    "principal": "作为授权主体的账户、成员或服务身份摘要。",
    "reason_code": "可供程序处理的稳定原因代码。",
    "region": "对象存储服务所在的区域标识。",
    "role_name": "角色的显示名称。",
    "root_prefix": "逻辑存储空间在对象存储中的受控根目录前缀。",
    "scope": "授权、查询或操作生效的资源范围。",
    "slug": "租户的稳定、可读标识，仅由小写字母、数字和连字符组成。",
    "source_id": "源资源的服务端唯一标识。",
    "source_key": "文件复制或移动操作的源规范相对对象路径。",
    "source_type": "授权、审计或操作来源的分类。",
    "sources": "用于得出当前权限或结果的来源列表。",
    "starts_at": "授权或支持访问开始生效的时间，采用 Asia/Shanghai（UTC+08:00）格式。",
    "system": "资源是否由系统内置并受额外修改限制。",
    "ttl_days": "资源或授权的有效天数。",
    "ttl_seconds": "临时 URL 或会话的有效秒数。",
    "type": "资源、错误或操作的类型标识。",
    "user": "全局用户账户的公开身份摘要。",
    "write_test_prefix": "连接探测时允许写入和清理测试对象的受控目录前缀。",
}


def _field_description(name: str) -> str:
    return FIELD_DESCRIPTIONS.get(name, f"“{name}”字段；具体取值和约束见当前资源说明。")


def document_openapi(schema: dict[str, Any]) -> dict[str, Any]:
    """Add deterministic Chinese prose without changing protocol semantics."""
    from s3mp.common.api.dependencies import OPERATION_PERMISSION_CLASSIFICATIONS

    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    # Global exception handlers are not visible to FastAPI's route-level
    # schema generation. Publish the real envelope explicitly so generated
    # clients never have to model error responses as `unknown`.
    schemas["ErrorEnvelope"] = {
        "type": "object",
        "title": "ErrorEnvelope",
        "description": "统一错误响应；所有非成功 API 响应均使用此信封。",
        "required": ["code", "message", "request_id"],
        "properties": {
            "code": {"type": "string", "description": "供程序判断的稳定错误代码。"},
            "message": {"type": "string", "description": "面向调用方的可读错误说明。"},
            "request_id": {"type": "string", "description": "本次请求的服务端追踪标识。"},
            "details": {
                "oneOf": [
                    {
                        "type": "object",
                        "additionalProperties": True,
                    },
                    {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                ],
                "description": "可选的结构化错误上下文或字段校验明细。",
            },
        },
    }
    from s3mp.metadata.catalog import (
        EFFECTS,
        OPERATIONS,
        QUOTA_SCOPES,
        SCOPES,
        STATUS_CATALOG,
        STORAGE_ADDRESSING,
    )

    def _enum_schema(title: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "type": "string",
            "title": title,
            "enum": [item["value"] for item in items],
            "description": "由 /api/v1/metadata/catalog 同步发布的稳定枚举值。",
        }

    for resource, items in STATUS_CATALOG.items():
        schemas[f"Metadata{resource.title().replace('_', '')}Status"] = _enum_schema(
            f"Metadata{resource.title().replace('_', '')}Status", items
        )
    schemas["MetadataAuthorizationScope"] = _enum_schema("MetadataAuthorizationScope", SCOPES)
    schemas["MetadataAuthorizationEffect"] = _enum_schema("MetadataAuthorizationEffect", EFFECTS)
    schemas["MetadataStorageOperation"] = _enum_schema("MetadataStorageOperation", OPERATIONS)
    schemas["MetadataQuotaScope"] = _enum_schema("MetadataQuotaScope", QUOTA_SCOPES)
    schemas["MetadataStorageAddressing"] = _enum_schema(
        "MetadataStorageAddressing", STORAGE_ADDRESSING
    )
    # These are shared, read-only contract building blocks.  They describe
    # server-derived state reused by storage, authorization and governance
    # responses; none contain an endpoint credential or secret-store locator.
    schemas["SharedStorageProfile"] = {
        "type": "object",
        "title": "SharedStorageProfile",
        "description": "平台唯一共享 S3 目标的脱敏运行摘要；物理连接参数仅由部署配置维护。",
        "required": ["bucket", "region", "path_style", "signature_version", "profile_version"],
        "properties": {
            "bucket": {"type": "string", "description": "所有租户与应用共同使用的服务端 Bucket。"},
            "region": {"type": "string", "description": "共享 S3 目标使用的区域标识。"},
            "path_style": {
                "type": "boolean",
                "description": "是否按 path-style 生成 S3 请求；生产和 MinIO 均可由部署配置启用。",
            },
            "signature_version": {
                "type": "string",
                "enum": ["s3v4"],
                "description": "S3 请求签名协议版本。",
            },
            "profile_version": {
                "type": "integer",
                "minimum": 1,
                "description": "共享目标配置版本；排队任务据此拒绝陈旧目标。",
            },
        },
    }
    schemas["ApplicationStorageNamespace"] = {
        "type": "object",
        "title": "ApplicationStorageNamespace",
        "description": (
            "由服务端固定的应用存储命名空间；调用方只能提供相对对象路径，不能提供物理 Key。"
        ),
        "required": ["application_id", "storage_namespace", "profile_version"],
        "properties": {
            "application_id": {
                "type": "string",
                "format": "uuid",
                "description": "命名空间所属应用标识。",
            },
            "storage_namespace": {"type": "string", "description": "不可变的服务端对象 Key 前缀。"},
            "profile_version": {
                "type": "integer",
                "minimum": 1,
                "description": "创建该命名空间时的共享 profile 版本。",
            },
        },
    }
    schemas["QuotaStatus"] = {
        "type": "object",
        "title": "QuotaStatus",
        "description": "租户或应用配额状态；可用容量为上限减去已用量与上传保留量。",
        "required": ["scope_type", "used_bytes", "reserved_bytes", "available_bytes"],
        "properties": {
            "scope_type": {
                "type": "string",
                "enum": ["tenant", "application"],
                "description": "配额统计范围。",
            },
            "limit_bytes": {
                "type": ["integer", "null"],
                "minimum": 0,
                "description": "允许使用和预留的容量上限。",
            },
            "used_bytes": {
                "type": "integer",
                "minimum": 0,
                "description": "已被对象存储验证并提交的容量。",
            },
            "reserved_bytes": {
                "type": "integer",
                "minimum": 0,
                "description": "进行中上传暂时保留的容量。",
            },
            "available_bytes": {
                "type": "integer",
                "minimum": 0,
                "description": "当前还能预留的容量。",
            },
            "measured_at": {
                "type": "string",
                "format": "date-time",
                "description": "本次用量读取或校准时间。",
            },
        },
    }
    schemas["QuotaReconciliationItem"] = {
        "type": "object",
        "title": "QuotaReconciliationItem",
        "description": "一次配额校准中某个租户或应用范围的结果；不包含对象内容或凭据。",
        "required": ["scope_type", "status"],
        "properties": {
            "scope_type": {
                "type": "string",
                "enum": ["tenant", "application"],
                "description": "被校准的配额范围。",
            },
            "status": {
                "type": "string",
                "enum": ["unchanged", "corrected", "quarantined", "failed"],
                "description": "该范围的校准结论。",
            },
            "actual_used_bytes": {
                "type": "integer",
                "minimum": 0,
                "description": "按已验证对象统计的实际已用容量。",
            },
            "reason_code": {
                "type": "string",
                "description": "冲突、隔离或失败时供程序处理的稳定原因代码。",
            },
        },
    }
    schemas["QuotaReconciliationResult"] = {
        "type": "object",
        "title": "QuotaReconciliationResult",
        "description": "配额校准任务汇总；用于运维任务输出，不代表对外文件内容接口。",
        "required": ["started_at", "completed_at", "items"],
        "properties": {
            "started_at": {
                "type": "string",
                "format": "date-time",
                "description": "校准任务开始时间。",
            },
            "completed_at": {
                "type": "string",
                "format": "date-time",
                "description": "校准任务结束时间。",
            },
            "items": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/QuotaReconciliationItem"},
                "description": "逐范围的校准结果。",
            },
        },
    }
    error_response = {
        "description": "请求未成功；响应遵循统一错误信封。",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
    }

    schema.setdefault("info", {})["description"] = (
        "S3MP 是面向多租户的受控文件存储服务。管理接口使用租户会话 Cookie "
        "`s3mp_session`；账户登录与平台控制接口使用账户会话 Cookie "
        "`s3mp_account_session`。浏览器发起变更请求时同时提交 `X-S3MP-CSRF`，"
        "服务端应用访问使用 API Key。错误响应统一返回稳定的 `code`、可读的 "
        "`message` 和用于排障的 `request_id`；任何会话值、API Key 或存储凭据均不会出现在响应中。"
    )
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"} or not isinstance(
                operation, dict
            ):
                continue
            operation_id = operation.get("operationId", "")
            description = OPERATION_DESCRIPTIONS.get(
                operation_id, "执行该公开 API 操作；具体输入、输出和授权要求见下方说明。"
            )
            operation["description"] = description
            responses = operation.setdefault("responses", {})
            for status_code in ("400", "401", "403", "404", "409", "412", "422", "500"):
                responses[status_code] = error_response
            operation["summary"] = OPERATION_SUMMARIES.get(
                operation_id, description.split("；", 1)[0]
            )
            permission = OPERATION_PERMISSION_CLASSIFICATIONS.get(operation_id)
            if permission is not None:
                operation["x-permission"] = permission
            for parameter in operation.get("parameters", []):
                if isinstance(parameter, dict) and isinstance(parameter.get("name"), str):
                    parameter_name = parameter["name"]
                    parameter["description"] = OPERATION_PARAMETER_DESCRIPTIONS.get(
                        (operation_id, parameter_name), _field_description(parameter_name)
                    )
    _document_node(schema)
    return schema


def _document_node(value: Any) -> None:
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            for name, property_schema in properties.items():
                if isinstance(property_schema, dict):
                    # Field() descriptions express resource-specific semantics
                    # (for example, shared-bucket namespaces). Do not replace
                    # them with a generic name-based sentence.
                    property_schema.setdefault("description", _field_description(name))
        for nested in value.values():
            _document_node(nested)
    elif isinstance(value, list):
        for nested in value:
            _document_node(nested)
