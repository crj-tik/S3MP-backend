---
type: attribution
id: attribution/<kebab-name>       # 如 attribution/agent-performance
title: <中文名，如 经纪人业绩归因框架>
resource: <uri，正文即内容时指向本文件>
owner: <业务专家/团队>
updated_at: 2026-07-13
status: draft
scope: enterprise
provenance: human
unit: [经纪]
business_domain: [贝壳城市]
business_line: [二手]
topic: [市场情况]
# application_scope: [智慧CA]       # 仅应用专属分析框架填写；缺失表示共享
scope_level: [城市]
analysis_methods: [趋势, 同比, 环比]
applies_to: [metric::<数字ID>]      # 适用的指标，可多个
factors: [metric::<数字ID>, table/<xxx>]  # 归因因子，指向 metric/table
# evaluation_rules:
#   - metric: metric::<数字ID>
#     rule_type: 阈值
#     operator: 大于等于
#     value: 0.5
#     value_unit: 比例
#     label: 高水平
#     when: {scope_level: [城市]}
#     basis: 业务标准
reviewed_by: <业务专家姓名>
tags: []
---

# Factors

<因子列表及权重/排查优先级/业务逻辑说明，逐条链接到对应卡片：>

1. [metric::<数字ID>](../metric/<数字ID>.md)：<为什么是因子、怎么解读>

# Analysis Method

<趋势、同比、环比、排名、结构或漏斗等分析步骤；说明方法适用前提。>

# Evaluation Rules

<解释 frontmatter 中阈值、参考均值、连续趋势规则的业务含义和误用边界。>

# Citations

<依据来源：访谈记录、复盘文档等链接。>
