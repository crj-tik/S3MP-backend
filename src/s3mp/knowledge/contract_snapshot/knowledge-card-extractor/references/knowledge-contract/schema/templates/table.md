---
type: table
id: table/<kebab-name>             # 如 table/deal-fact
title: <中文表名，如 成交流水表>
resource: warehouse://<db.table>
owner: <维护方，如 数据工程>
updated_at: 2026-07-13
status: draft
scope: enterprise
provenance: human
unit: [经纪]
business_domain: [贝壳城市]        # 受控词表：北京链家 | 贝壳城市 | 通用
application_scope: []               # 应用专属表显式填写；留空表示跨应用共享
business_line: [二手]
layer: 明细
time_grain: [日]
lifecycle: 生产
queryable: 可查
business_objects:
  - {object: 成交, role: 主对象}
schema_ref: <uri>                  # 实际字段定义所在（数仓元数据/DDL）
refresh_freq: <如 日更 T+1>
tags: []
---

# Schema

<字段列表及业务含义（关键字段即可，全量以 schema_ref 为准）：>

| 字段 | 类型 | 含义 |
|---|---|---|
| | | |

# Join Path

<与其他表的关联方式，链接指向对应表卡，写明 join keys：>

- [table/<xxx>](../table/<xxx>.md)：`<本表.key> = <对方表.key>`
