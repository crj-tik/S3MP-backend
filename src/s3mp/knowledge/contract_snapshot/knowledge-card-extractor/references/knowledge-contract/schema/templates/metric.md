---
type: metric
id: metric::<指标平台数字ID>        # 全局唯一，如 metric::25713
title: <中文指标名>
resource: metric-platform://metric::<指标平台数字ID>  # 指标平台事实源
owner: <维护方，如 数据工程-销售域>
updated_at: 2026-07-13
status: draft
scope: enterprise
provenance: human
unit: [经纪]                       # 受控词表
business_domain: [贝壳城市]        # 受控词表：北京链家 | 贝壳城市 | 通用
business_line: [二手]              # 受控词表
topic: [业绩]                      # 受控词表，可多值
canonical_name: "<源系统规范名，如 纯新签单量*COO二手买卖*贝联_月>"  # 可选；无权威来源则删除本行
formula: "<SUM(...) WHERE ...>"
value_continuity: 连续              # 可选：离散 | 连续；只指导评价方法
dimensions: [城市, 门店, 经纪人, 时间粒度]
default: true                      # 是否默认口径
depends_on: [table/<xxx>]          # 依赖的表卡 id
# variant_of: metric::<数字ID>      # 口径变体时填，指向指标族默认节点
tags: []
---

# Definition

<指标说明：衡量什么、业务意义、适用分析场景。多口径时写明差异原因，并链接 variant 卡片。>

# Business Definition

<可选。业务口径长文本：统计对象/事件、时间范围、纳入与排除条件、有效状态、去重规则、统计粒度、特殊边界。无权威来源则删除本章节，不编造。>

# Examples

<典型查询示例：什么问题 → 怎么过滤/分组/聚合。>
