---
type: org
id: org/<kebab-name>               # 如 org/hierarchy、org/term-alias
title: <中文名，如 组织层级 / 业务术语表>
resource: <uri>
owner: <数据治理/HR/大数据中心>
updated_at: 2026-07-13
status: draft
scope: enterprise
provenance: human
source_system: <原系统，如 CRM / HR / 取数工具>
tags: []
---

# Mapping

<按卡片用途选择一种：>

<组织层级：城市 → 大区/大部 → CA → 事业部 → 门店/店组 → 经纪人>

<名称→编码映射：>

| 名称 | 编码 |
|---|---|
| 成都 | <city_code> |

<别名映射（alias_of，query 归一化用）：>

| 别名/黑话 | 标准词 | 说明 |
|---|---|---|
| 买卖 | 二手 | 业务词标准化 |
| 未开单 | 新签单量 | 状态黑话还原 |
