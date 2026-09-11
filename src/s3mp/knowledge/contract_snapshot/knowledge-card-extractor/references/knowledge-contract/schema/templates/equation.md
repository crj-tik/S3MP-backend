---
type: equation
id: equation/<kebab-name>          # 如 equation/perf-decomp
title: <中文名，如 二手业绩奇妙等式>
resource: <uri，正文即内容时指向本文件>
owner: <业务专家/团队>
updated_at: 2026-07-13
status: draft
scope: enterprise
provenance: human
unit: [经纪]
business_domain: [贝壳城市]
business_line: [二手]
topic: [经营结果]
# application_scope: [智慧CA]       # 仅应用专属等式填写；缺失表示共享
result: metric::<数字ID>            # 等式左边的指标
factors:                           # 等式右边的因子，带语义或操作数角色
  - { id: metric::<数字ID>, role: 量 }
  - { id: metric::<数字ID>, role: 价 }
operator: 乘法                     # 乘法 | 加法 | 除法 | 减法
tags: []
---

# Decomposition

<拆解逻辑、适用的分析视角（管理视角/作业视角）。>

# Priority

<分析时各因子的排查优先级及理由。>
