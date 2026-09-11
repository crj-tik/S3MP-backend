---
type: action
id: action/<kebab-name>            # 如 action/increase-channel-ads
title: <中文名，如 加大渠道投放>
resource: <uri，正文即内容时指向本文件>
owner: <业务专家/团队>
updated_at: 2026-07-13
status: draft
scope: enterprise
provenance: human
unit: [经纪]
business_line: [二手]
responds_to:                       # 触发条件：哪个指标、什么状态
  - { metric: metric::<数字ID>, condition: 下降, threshold: "<如 环比 -10%>" }
owner_role: <执行责任方，如 门店店长>
tags: []
---

# Playbook

<具体做什么，分步骤。>

# Applicability

<适用范围与前提，不适用的情况。>
