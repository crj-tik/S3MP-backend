---
type: "org"
id: "org/codelist-contract-status"
title: "合同状态码字典"
resource: "knowledge/org/codelist-contract-status.md"
owner: "数据工程（待指派）"
updated_at: "2026-08-16"
status: "draft"
provenance: "ai_suggested"
source_system: "交易中台"
business_domain:
- "通用"
---

# Mapping

| code | 名称 | 业务含义 | 是否计入成交 |
|---|---|---|---|
| 2 | 合同-签约 | 已签订正式合同 | ✓ |
| 3 | 合同-过户 | 已完成过户 | ✓ |
| 6 | 合同-完结 | 全流程完结 | ✓ |
| 5 | 合同-解约 | 已解约，佣金按解约规则处理 | ✗ |
| 302 | 意向金-下意向 | 仅下意向金，尚未签约 | ✗ |
| 202 | 定金-下定金 | 仅下定金，尚未签约 | ✗ |

# Usage Notes

**最后一列"是否计入成交"，是 `concept/chengjiao` 落到物理字段的那一跳。**

概念卡说清"二手的成交 = 签约"，本字典卡说清"签约 = `status_code ∈ {2, 3, 6}`"，
两张卡合起来才让 Agent 能把业务词翻译成 WHERE 条件：

```
用户说"成交"
  → concept/chengjiao  senses[business_line=二手].means = 签约
  → 本卡              签约 = status_code IN (2, 3, 6)
  → SQL               WHERE status_code IN (2, 3, 6)
```

缺任何一跳，Agent 都只能靠猜。

# Why Not In The Table Card

`status_code` 这套值在多张成交类表里重复出现。留在表卡正文里必然各抄各的、各自漂移，
且它本身并不属于任何一张表——它属于交易中台这个源系统。

因此约定：**字段留在表卡正文，跨表复用的枚举抽出来建 `org/codelist-*` 卡**，
表卡 Schema 表格第 5 列填本卡 id，不在表内展开枚举值。
