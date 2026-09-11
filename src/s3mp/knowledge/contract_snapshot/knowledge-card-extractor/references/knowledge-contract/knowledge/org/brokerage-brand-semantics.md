---
type: org
id: org/brokerage-brand-semantics
title: 经纪业务品牌分类语义
description: 链家、链家H、德佑、KA、直营、加盟、自有品牌和贝联的业务分类关系
resource: knowledge/org/brokerage-brand-semantics.md
owner: 智慧CA业务方（待指派）
updated_at: 2026-08-24
status: draft
scope: enterprise
provenance: ai_extracted
source_ref: attachment://smart-ca-brokerage-track-one-ontology-semantics#平台和品牌
source_system: 智慧CA业务总结
unit: [经纪]
business_domain: [贝壳城市]
business_line: [二手, 新房, 租赁]
tags: [品牌分类, 贝联]
---

# Mapping

| 术语 | 业务含义 |
|---|---|
| 子品牌、品牌 | 与贝壳合作的具体品牌名称，如链家、德佑、21世纪不动产 |
| 链家 | 贝壳平台直营品牌 |
| 链家H | 可使用链家品牌，但由品牌方自行管理的特殊加盟模式，可包含多个子品牌 |
| 德佑 | 贝壳自有加盟品牌 |
| KA | 除链家、链家H、德佑以外的其他子品牌集合 |
| 直营品牌 | 当前仅链家；并非所有业城都有链家 |
| 加盟品牌 | 非直营品牌，包括德佑、21世纪不动产等 |
| 自有品牌、平台控股品牌 | 文档列举德佑、中环、住商、乐远、邦房、优铭佳、置家、枫邻 |
| 贝联 | 德佑与KA的合并统计范围 |

# Notes

- 原文“品牌类型分为三类”后列出链家、链家H、德佑、KA四项，存在数量表述冲突；本卡保留四项，待 owner 审核。
- `贝联 = 德佑 + KA` 与现有过滤词表一致，可作为统计范围展开；其他分类不自动改写查询条件。
- 自有品牌名单具有时效性，当前卡为 draft，不应在 owner 审核前驱动硬过滤。
