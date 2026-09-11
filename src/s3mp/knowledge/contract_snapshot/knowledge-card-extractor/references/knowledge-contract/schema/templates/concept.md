---
type: "concept"
id: "concept/<kebab-case-name>"
title: "<业务词本身，如 成交>"
resource: "knowledge/concept/<kebab-case-name>.md"   # 事实源是卡片自身
owner: "<业务专家>"                                   # 必须是业务专家，不是数据工程
updated_at: "YYYY-MM-DD"
status: "draft"
provenance: "human"

ambiguous: true               # 是否存在跨分面歧义；true 时 senses 必须 ≥2
disambiguation: "required"    # required | default | none —— 用户未指明分面时怎么办
# default_sense: "<分支名>"   # disambiguation=default 时必填

senses:                       # 语义分支（→ means_in 边）
  - condition: { business_line: "新房" }   # 生效条件，键必须取自受控分面
    means: "认购"                          # 该条件下这个词实际指什么
    metrics: []                            # 对应的权威指标卡 id
    codelist: null                         # 落到物理编码的那一跳，如 org/codelist-contract-status
    predicate: null                        # 落到 WHERE 条件的那一跳，如 status_code IN (2,3,6)
    note: "<业务解释>"
  - condition: { business_line: "二手" }
    means: "签约"
    metrics: []
    codelist: null
    predicate: null
    note: "<业务解释>"
---

# Senses

每个语义分支的完整解释：业务上为什么这么定义、边界在哪。

> **端到端要求**：只写清"这个词指哪个指标"是不够的。Agent 最终要把业务词翻译成
> WHERE 条件，所以每个分支都应能走通
> `用户词 → sense → metric → table/column → codelist → predicate` 这条链。
> 缺任何一跳，校验器会告警。

# Disambiguation

Agent 遇到该词该如何处理：回问用户 / 用默认 / 同时给出两个口径。

# Common Mistakes

这个词历史上被用错的典型场景。**这是本卡最有复用价值的部分**，
写具体的错法和后果，不要写"要注意区分口径"这类空话。
