"""Stable, non-sensitive enum metadata shared by the API and OpenAPI docs."""

from collections.abc import Sequence
from enum import StrEnum
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


class CatalogDescriptor(BaseModel):
    """Declares where a catalog enum is used by the public API."""

    model_config = ConfigDict(extra="forbid")

    domain: str
    resource: str
    field: str
    query_parameter: str | None = None
    used_by: list[str] = Field(default_factory=list)
    items: list[CatalogItem]


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
    domains: list[str] = Field(description="本响应包含的业务域。")
    catalog: list[CatalogDescriptor] = Field(
        description="枚举的资源、字段、查询参数和支持接口用途映射。"
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
    "file_object": [
        _item("available", "可用", "文件已入库并可按授权访问。", ("deleting", "quarantined")),
        _item("deleting", "删除中", "文件已进入受控删除流程。", ("deleted", "delete_failed")),
        _item(
            "delete_failed",
            "删除失败",
            "文件删除需要重试或人工处理。",
            ("deleting", "quarantined"),
        ),
        _item("deleted", "已删除", "文件已完成 provider 删除并释放配额。", terminal=True),
        _item("quarantined", "已隔离", "文件因无法证明安全归属而不可被业务访问。", terminal=True),
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
        _item(
            "reserved",
            "已预留",
            "容量已被进行中的上传占用。",
            ("settled", "released", "quarantined"),
        ),
        _item("settled", "已结算", "预留已按实际对象大小结算。", terminal=True),
        _item("released", "已释放", "预留已释放回可用容量。", terminal=True),
        _item("quarantined", "已隔离", "预留关联异常，需要人工或对账处理。", terminal=True),
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
    _item("storage_space", "存储空间", "统计单个逻辑存储空间命名空间的容量。"),
]
STORAGE_ADDRESSING = [
    _item("path", "Path-style", "使用 /bucket/key 形式访问 S3 兼容服务。"),
    _item("virtual", "Virtual-hosted-style", "使用 bucket.endpoint/key 形式访问 S3。"),
]

DOMAIN_NAMES = (
    "identity",
    "lifecycle",
    "authorization",
    "storage",
    "file",
    "ingestion",
    "quota",
    "governance",
)


def _enum_values(enum_type: type[StrEnum]) -> set[str]:
    return {item.value for item in enum_type}


def _descriptor(
    domain: str,
    resource: str,
    field: str,
    items: list[dict[str, Any]],
    *used_by: str,
    query_parameter: str | None = None,
) -> dict[str, Any]:
    return {
        "domain": domain,
        "resource": resource,
        "field": field,
        "query_parameter": query_parameter,
        "used_by": list(used_by),
        "items": [dict(item) for item in items],
    }


def _catalog_descriptors() -> list[dict[str, Any]]:
    """Build the public usage map from the same enum-backed catalog source."""
    from s3mp.applications.infrastructure.models import ApiKeyStatus, ApplicationStatus
    from s3mp.authorization.domain.evaluator import Decision
    from s3mp.authorization.infrastructure.models import BindingEffect
    from s3mp.files.domain.file_operations import MultipartStatus, OperationStatus
    from s3mp.files.domain.file_status import FileObjectStatus
    from s3mp.files.domain.ingestion import IngestionEventType, IngestionStatus
    from s3mp.governance.domain.access_review import (
        ApprovalRequestStatus,
        ReviewItemVerdict,
        ReviewStatus,
    )
    from s3mp.governance.domain.quota import ReservationStatus
    from s3mp.governance.domain.scanner import FindingSeverity, FindingType
    from s3mp.governance.domain.security_monitor import AlertCategory, AlertSeverity
    from s3mp.identity.infrastructure.models import MembershipStatus, PrincipalType, UserStatus
    from s3mp.platform.domain.support_access import SupportAccessStatus
    from s3mp.platform.infrastructure.models import TenantLifecycleStatus
    from s3mp.storage.domain.policy import StorageOperation

    enum_checks = {
        "user": UserStatus,
        "membership": MembershipStatus,
        "tenant": TenantLifecycleStatus,
        "ingestion": IngestionStatus,
        "multipart": MultipartStatus,
        "file_operation": OperationStatus,
        "reservation": ReservationStatus,
        "application": ApplicationStatus,
        "api_key": ApiKeyStatus,
        "file_object": FileObjectStatus,
        "support_access": SupportAccessStatus,
    }
    for resource, enum_type in enum_checks.items():
        actual = _enum_values(enum_type)
        declared = {item["value"] for item in STATUS_CATALOG[resource]}
        if actual != declared:
            raise RuntimeError(f"metadata catalog drift for {resource}: {actual ^ declared}")

    def enum_items(enum_type: type[StrEnum]) -> list[dict[str, Any]]:
        return [
            _item(member.value, member.value, f"稳定枚举值：{member.value}。")
            for member in enum_type
        ]

    return [
        _descriptor(
            "identity",
            "principal",
            "type",
            enum_items(PrincipalType),
            "GET /api/v1/users",
            query_parameter="principal_type",
        ),
        _descriptor(
            "identity",
            "user",
            "status",
            STATUS_CATALOG["user"],
            "GET /api/v1/users",
            query_parameter="status",
        ),
        _descriptor(
            "identity",
            "membership",
            "status",
            STATUS_CATALOG["membership"],
            "GET /api/v1/members",
            query_parameter="status",
        ),
        _descriptor(
            "lifecycle",
            "tenant",
            "status",
            STATUS_CATALOG["tenant"],
            "GET /api/v1/platform/tenants",
            query_parameter="status",
        ),
        _descriptor(
            "lifecycle",
            "application",
            "status",
            STATUS_CATALOG["application"],
            "GET /api/v1/applications",
            query_parameter="status",
        ),
        _descriptor(
            "lifecycle",
            "api_key",
            "status",
            STATUS_CATALOG["api_key"],
            "GET /api/v1/applications/{application_id}/api_keys",
            query_parameter="status",
        ),
        _descriptor(
            "storage",
            "storage_connection",
            "status",
            STATUS_CATALOG["storage_connection"],
            "GET /api/v1/storage_connections",
            query_parameter="status",
        ),
        _descriptor(
            "storage",
            "storage_space",
            "status",
            STATUS_CATALOG["storage_space"],
            "GET /api/v1/storage_spaces",
            query_parameter="status",
        ),
        _descriptor(
            "governance",
            "support_access",
            "status",
            STATUS_CATALOG["support_access"],
            "GET /api/v1/platform/support-access",
            query_parameter="status",
        ),
        _descriptor("storage", "operation", "operation", enum_items(StorageOperation)),
        _descriptor(
            "authorization",
            "binding",
            "effect",
            enum_items(BindingEffect),
            query_parameter="effect",
        ),
        _descriptor(
            "authorization",
            "decision",
            "decision",
            enum_items(Decision),
            query_parameter="decision",
        ),
        _descriptor(
            "authorization",
            "scope",
            "scope",
            SCOPES,
            query_parameter="scope",
        ),
        _descriptor(
            "authorization",
            "binding",
            "effect",
            EFFECTS,
            query_parameter="effect",
        ),
        _descriptor("file", "file_object", "status", STATUS_CATALOG["file_object"],
                    "GET /api/v1/storage_spaces/{space_id}/files", query_parameter="status"),
        _descriptor(
            "file",
            "upload",
            "status",
            STATUS_CATALOG["upload"],
            query_parameter="status",
        ),
        _descriptor(
            "file",
            "multipart",
            "status",
            enum_items(MultipartStatus),
            query_parameter="status",
        ),
        _descriptor(
            "file",
            "file_operation",
            "status",
            enum_items(OperationStatus),
            query_parameter="status",
        ),
        _descriptor(
            "ingestion",
            "ingestion",
            "status",
            enum_items(IngestionStatus),
            query_parameter="status",
        ),
        _descriptor(
            "ingestion",
            "ingestion_event",
            "event_type",
            enum_items(IngestionEventType),
            query_parameter="event_type",
        ),
        _descriptor(
            "quota", "quota", "scope", QUOTA_SCOPES, "GET /api/v1/quotas", query_parameter="scope"
        ),
        _descriptor("quota", "reservation", "status", enum_items(ReservationStatus)),
        _descriptor(
            "storage",
            "addressing",
            "mode",
            STORAGE_ADDRESSING,
            "GET /api/v1/storage_connections",
        ),
        _descriptor(
            "governance",
            "review",
            "status",
            enum_items(ReviewStatus),
            query_parameter="status",
        ),
        _descriptor(
            "governance",
            "review_item",
            "verdict",
            enum_items(ReviewItemVerdict),
            query_parameter="verdict",
        ),
        _descriptor(
            "governance",
            "approval_request",
            "status",
            enum_items(ApprovalRequestStatus),
            query_parameter="status",
        ),
        _descriptor(
            "governance",
            "alert",
            "severity",
            enum_items(AlertSeverity),
            query_parameter="severity",
        ),
        _descriptor(
            "governance",
            "alert",
            "category",
            enum_items(AlertCategory),
            query_parameter="category",
        ),
        _descriptor(
            "governance",
            "finding",
            "severity",
            enum_items(FindingSeverity),
            query_parameter="severity",
        ),
        _descriptor(
            "governance",
            "finding",
            "type",
            enum_items(FindingType),
            query_parameter="type",
        ),
    ]


def catalog_payload(domains: Sequence[str] | None = None) -> dict[str, Any]:
    """Return a fresh payload so callers cannot mutate the shared source."""
    selected = set(domains or DOMAIN_NAMES)
    unknown = selected.difference(DOMAIN_NAMES)
    if unknown:
        raise ValueError(f"unknown metadata domains: {sorted(unknown)}")
    descriptors = [item for item in _catalog_descriptors() if item["domain"] in selected]
    resources = {item["resource"] for item in descriptors}
    return {
        "version": CATALOG_VERSION,
        "statuses": {
            key: [dict(item) for item in items]
            for key, items in STATUS_CATALOG.items()
            if key in resources or key in {"user", "membership", "tenant", "application", "api_key"}
        },
        "scopes": [dict(item) for item in SCOPES] if "authorization" in selected else [],
        "effects": [dict(item) for item in EFFECTS] if "authorization" in selected else [],
        "operations": [dict(item) for item in OPERATIONS] if "storage" in selected else [],
        "quota_scopes": [dict(item) for item in QUOTA_SCOPES] if "quota" in selected else [],
        "storage_addressing": [dict(item) for item in STORAGE_ADDRESSING]
        if "storage" in selected
        else [],
        "domains": sorted(selected),
        "catalog": descriptors,
    }
