---
type: "policy"
id: "policy/<kebab-case-name>"
title: "<管控策略名称>"
resource: "knowledge/policy/<kebab-case-name>.md"    # 事实源是卡片自身
owner: "<数据安全 / 合规责任人>"                       # 必须是数据安全/合规，不是数据工程
updated_at: "YYYY-MM-DD"
status: "draft"
provenance: "human"

policy_kind: "安全"            # 安全 | 权限 | 质量 | 生命周期
severity: "禁止"               # 禁止 | 受限 | 提示
handling: "不可见"             # 不可见 | 可见不可查 | 需脱敏 | 需授权

match:                        # 三级证据，优先级：显式点名 > 含义列 > 字段名
  column_matches:             # 字段名正则
    - "<pattern>"
  meaning_matches:            # 含义列关键词正则 —— 不是可选增强项，是必需项
    - "<pattern>"             # JSON 打包 PII 字段名里没有敏感词，纯字段名匹配 100% 漏检
  columns:                    # 显式点名（表 + 字段）
    - { table: "table/hive.xxx", column: "yyy" }
  tables: []                  # 整表级管控

exemptions: []                # 豁免必须留痕：reason / approved_by / expires_at 三项缺一不可
# - table: "table/hive.xxx"
#   column: "yyy"
#   reason: "内部风控核验必需"
#   approved_by: "<审批人>"
#   expires_at: "YYYY-MM-DD"   # 无限期豁免不予通过；过期自动失效

masking: null                 # handling=需脱敏 时必填，说明脱敏方式（如 张*）
legal_basis: "<法规条款 / 公司制度编号>"
agent_message: "<Agent 遇到该字段时对用户怎么说，含替代途径>"
---

# Scope

管控范围的业务解释：为什么这类字段受管，边界在哪，哪些看起来像但不属于本策略。

# Handling

处置细则，含允许的替代方案（例："需要联系经纪人时走工单系统，不要取手机号"）。

> ⚠️ 本策略作用于**知识返回层**——控制字段说明是否出现在知识包里。
> 它不是数据访问控制边界，拦不住 Agent 已知字段名后直接写 SQL。
> 真正的执行点在取数端的列级/行级授权与审计。见 `krc/policy.py` 的能力边界声明。

# Exemption Process

豁免怎么申请、谁批、复核周期。
