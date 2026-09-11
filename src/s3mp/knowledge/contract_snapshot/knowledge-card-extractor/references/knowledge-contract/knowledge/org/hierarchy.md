---
type: org
id: org/hierarchy
title: 组织层级与维度消歧
description: 组织维度下钻链（metric 卡 dimensions 受控来源）、维度消歧优先级 dim_priority
resource: ../../参考资料/knowledge.json
owner: 大数据中心（待业务专家确认）
updated_at: 2026-07-13
status: draft
scope: enterprise
provenance: ai_extracted
source_system: 取数工具（dwh_klg_rule / knowledge.json）
source_ref: ../../参考资料/knowledge.json
unit: [经纪]
tags: [组织, 层级, 维度]
---

> 本卡由 scripts/extract_legacy_rules.py 从存量规则自动提炼（2026-07-13），改规则请改源文件后重跑脚本。

# Mapping

## 组织层级（下钻链）

```
城市 → 大区/大部 → CA → 事业部 → 门店/店组 → 经纪人
```

metric 卡 `dimensions` 的受控词表见 ontology/vocabularies.yaml（dimensions，v1.3 起）：
组织维度规范名与下方 dim_priority 用词一致（如"大区"，不写链节点合并名"大区/大部"），
另加时间粒度与业务维度白名单（渠道等）。

## 维度消歧优先级（dim_priority，从高到低）

问题中出现多个维度词时，按此序消歧：靠前的作过滤，最细的组织粒度作分组。

区域、城市等级、业绩城市、城市总、城市总系统号、地理城市、品牌、子品牌、品牌公司名称、事业部、事业部总、事业部总系统号、大部、运营总、运营总系统号、大区、CAD、CAD系统号、CA、CA系统号、商圈、门店、门店编码、店组、经纪人、经纪人系统号、职位类别名称

示例："成都哪个经纪人业绩好" → 过滤: 城市=成都，分组: 经纪人。

## 城市名 → 编码

⚠️ 存量规则未含城市编码映射，待源系统（组织主数据）接入后补充。
