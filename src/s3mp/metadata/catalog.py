"""Stable, non-sensitive enum metadata shared by the API and OpenAPI docs."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

CATALOG_VERSION = "v1"


class CatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(description="稳定的程序值；前端请求和状态判断使用此值。")
    label: str = Field(description="面向用户展示的中文名称。")
    description: str = Field(description="该值的业务含义和使用边界。")
    terminal: bool = Field(description="是否为不可继续流转的终态。")
    transitions: list[str] = Field(
        default_factory=list,
        description="当前值允许转换到的下一状态值；空数组表示没有可用转换。",
    )


class MetadataCatalogResponse(BaseModel):
    """前端状态下拉、筛选和状态操作使用的非敏感元数据目录。"""

    version: str = Field(description="目录版本；值集合变化时递增。")
    statuses: dict[str, list[CatalogItem]] = Field(description="按资源类型分组的生命周期状态目录。")
    scopes: list[CatalogItem] = Field(description="授权资源范围类型目录。")
    effects: list[CatalogItem] = Field(description="授权效果目录。")
    operations: list[CatalogItem] = Field(description="文件和对象存储操作类型目录。")
    quota_scopes: list[CatalogItem] = Field(description="配额统计范围目录。")
    storage_addressing: list[CatalogItem] = Field(
        description="对象存储寻址方式目录；不包含端点或凭据。"
    )


def _item(
    value: str,
    label: str,
    description: str,
    transitions: tuple[str, ...] = (),
    *,
    terminal: bool = False,
) -> dict[str, Any]:
    return {
        "value": value,
        "label": label,
        "description": description,
        "terminal": terminal,
        "transitions": list(transitions),
    }


STATUS_CATALOG: dict[str, list[dict[str, Any]]] = {
    "user": [
        _item("active", "正常", "账户可以登录和使用平台。", ("disabled", "deleted")),
        _item("disabled", "已禁用", "账户不能登录。", ("active", "deleted")),
        _item("deleted", "已删除", "账户已软删除，仅保留合规记录。", terminal=True),
    ],
    "membership": [
        _item("invited", "已邀请", "已建立成员关系但尚未完成激活。", ("active", "removed")),
        _item("active", "正常", "成员可以在租户内使用被授予的权限。", ("suspended", "removed")),
        _item("suspended", "已暂停", "成员暂时不能使用租户权限。", ("active", "removed")),
        _item("removed", "已移除", "成员关系已结束。", terminal=True),
    ],
    "tenant": [
        _item("active", "正常", "租户可进行管理和文件业务。", ("suspended", "deleted")),
        _item("suspended", "已暂停", "租户业务请求被阻止，但数据保留。", ("active", "deleted")),
        _item("deleted", "已删除", "租户已软删除。", terminal=True),
    ],
    "application": [
        _item(
            "active",
            "正常",
            "应用可以使用 API Key 和文件存储能力。",
            ("suspended", "pending_takeover", "deleted"),
        ),
        _item("suspended", "已暂停", "应用暂时不能进行文件操作。", ("active", "deleted")),
        _item(
            "pending_takeover",
            "待接管",
            "应用没有有效所有者，等待具备管理权限的成员接管。",
            ("active", "deleted"),
        ),
        _item("deleted", "已删除", "应用已软删除。", terminal=True),
    ],
    "api_key": [
        _item("active", "有效", "API Key 可以代表所属应用调用接口。", ("revoked", "expired")),
        _item("revoked", "已撤销", "API Key 不能继续调用接口。", terminal=True),
        _item("expired", "已过期", "API Key 已超过有效期。", terminal=True),
    ],
    "upload": [
        _item(
            "pending",
            "待上传",
            "上传会话已创建，等待内容写入。",
            ("completed", "cancelled", "expired"),
        ),
        _item("completed", "已完成", "上传对象已验证并完成入库。", terminal=True),
        _item("cancelled", "已取消", "上传会话已取消。", terminal=True),
        _item("expired", "已过期", "上传会话已超过有效期。", terminal=True),
        _item("failed", "失败", "上传或验证失败。", terminal=True),
    ],
    "multipart": [
        _item(
            "pending",
            "进行中",
            "分片上传仍可继续。",
            ("completing", "aborted", "expired", "failed"),
        ),
        _item("completing", "合并中", "正在向对象存储提交分片合并。", ("completed", "failed")),
        _item("completed", "已完成", "分片对象已验证并完成入库。", terminal=True),
        _item("aborted", "已中止", "分片上传已中止。", terminal=True),
        _item("expired", "已过期", "分片上传已超过有效期。", terminal=True),
        _item("failed", "失败", "分片上传或验证失败。", terminal=True),
    ],
    "file_operation": [
        _item(
            "pending",
            "待处理",
            "异步文件操作等待 worker 执行。",
            ("completed", "partial_failure", "failed"),
        ),
        _item("completed", "已完成", "异步文件操作已完成。", terminal=True),
        _item("partial_failure", "部分失败", "操作部分完成，需要人工或重试处理。", terminal=True),
        _item("failed", "失败", "异步文件操作执行失败。", terminal=True),
    ],
    "support_access": [
        _item("pending", "待审批", "支持访问请求等待审批。", ("approved", "revoked", "expired")),
        _item("approved", "已批准", "支持访问已被物化为限时授权。", ("revoked", "expired")),
        _item("revoked", "已撤销", "支持访问已撤销。", terminal=True),
        _item("expired", "已过期", "支持访问已超过有效期。", terminal=True),
    ],
    "storage_connection": [
        _item("active", "正常", "受管对象存储关联记录可被读取。", ("suspended", "deleted")),
        _item("suspended", "已暂停", "对象存储关联记录暂不可用。", ("active", "deleted")),
        _item("deleted", "已删除", "对象存储关联记录已软删除。", terminal=True),
    ],
    "storage_space": [
        _item("active", "正常", "逻辑存储空间可用于文件操作。", ("suspended", "deleted")),
        _item("suspended", "已暂停", "逻辑存储空间暂时不能进行文件操作。", ("active", "deleted")),
        _item("deleted", "已删除", "逻辑存储空间已软删除。", terminal=True),
    ],
    "ingestion": [
        _item(
            "initiated",
            "已创建",
            "已记录上传意图，等待内容处理。",
            ("uploading", "verified", "failed", "expired"),
        ),
        _item(
            "uploading",
            "上传中",
            "正在接收或验证对象内容。",
            ("verification_pending", "failed", "expired"),
        ),
        _item("verification_pending", "待验证", "等待对象存储元数据校验。", ("verified", "failed")),
        _item("verified", "已验证", "对象内容和目标已通过验证。", ("committed", "failed")),
        _item(
            "committed", "已提交", "文件元数据已提交。", ("available", "reconciliation_required")
        ),
        _item("available", "可用", "文件可被授权主体访问。", terminal=True),
        _item("failed", "失败", "入库流程失败。", terminal=True),
        _item("expired", "已过期", "入库意图已过期。", terminal=True),
        _item(
            "reconciliation_required", "待对账", "需要后台对账或人工处理。", ("available", "failed")
        ),
    ],
    "reservation": [
        _item("reserved", "已预留", "容量已被进行中的上传占用。", ("settled", "released")),
        _item("settled", "已结算", "预留已按实际对象大小结算。", terminal=True),
        _item("released", "已释放", "预留已释放回可用容量。", terminal=True),
    ],
}

SCOPES = [
    _item("tenant", "租户", "覆盖租户管理范围。"),
    _item("storage_space", "存储空间", "覆盖一个应用逻辑存储空间。"),
    _item("directory", "应用目录", "仅覆盖应用命名空间内的规范相对目录。"),
]
EFFECTS = [
    _item("allow", "允许", "授予匹配范围内的权限。"),
    _item("deny", "拒绝", "拒绝匹配范围内的权限，且优先于 allow。"),
]
OPERATIONS = [
    _item("LIST", "列举", "列举授权范围内的文件对象。"),
    _item("HEAD", "读取元数据", "读取对象元数据。"),
    _item("GET", "读取内容", "读取对象内容或签发下载地址。"),
    _item("PUT", "写入内容", "写入或上传对象内容。"),
    _item("DELETE", "删除对象", "删除授权范围内的对象。"),
]
QUOTA_SCOPES = [
    _item("tenant", "租户", "统计租户全部应用的容量。"),
    _item("application", "应用", "统计单个应用命名空间的容量。"),
]
STORAGE_ADDRESSING = [
    _item("path", "Path-style", "使用 /bucket/key 形式访问 S3 兼容服务。"),
    _item("virtual", "Virtual-hosted-style", "使用 bucket.endpoint/key 形式访问 S3。"),
]


def catalog_payload() -> dict[str, Any]:
    """Return a fresh payload so callers cannot mutate the shared source."""
    return {
        "version": CATALOG_VERSION,
        "statuses": {key: [dict(item) for item in items] for key, items in STATUS_CATALOG.items()},
        "scopes": [dict(item) for item in SCOPES],
        "effects": [dict(item) for item in EFFECTS],
        "operations": [dict(item) for item in OPERATIONS],
        "quota_scopes": [dict(item) for item in QUOTA_SCOPES],
        "storage_addressing": [dict(item) for item in STORAGE_ADDRESSING],
    }
