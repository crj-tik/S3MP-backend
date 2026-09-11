---
type: org
id: org/brokerage-organization
title: 经纪业务组织与角色语义
description: 智慧CA业务分析使用的贝壳管理组织、CA作业组织及管理角色映射
resource: knowledge/org/brokerage-organization.md
owner: 智慧CA业务方（待指派）
updated_at: 2026-08-24
status: draft
scope: enterprise
provenance: ai_extracted
source_ref: attachment://smart-ca-brokerage-track-one-ontology-semantics#贝壳组织架构
source_system: 智慧CA业务总结
unit: [经纪]
business_domain: [贝壳城市]
business_line: [二手, 新房, 租赁]
tags: [组织层级, 管理角色, CA]
---

# Mapping

## 贝壳管理链

```text
贝壳城市(COO)
  -> 区域/战区(区域总/战区总)
    -> 业城(城市总)
      -> 事业部
        -> 运营事业部/贝联事业部(运营总)
        -> 链家事业部(链家总)
        -> 新房事业部(新房总)
```

- 地城是地理城市，无对应管理角色；一个业城可包含多个地城。
- 中心城市是区域内由城市总直接管理的核心业城。

## CA作业链

```text
大部(运营总)
  -> 大区(CAD)
    -> CA区域(CA/区域经理)
      -> 赋能区域
        -> 商圈/业务商圈/考核商圈(商圈经理/圈经)
          -> 门店
            -> 经纪人
```

- 文档称 CA 是贝壳平台最小的一线业务作业单位；门店是加盟的最小单位；经纪人是最小作业单元。
- 赋能区域与商圈、CA区域与赋能区域在多数情况下是一对一，但语义上仍是不同层级，不能直接合并编码。

## 加盟关系

加盟商是门店工商注册公司，一个加盟商可管理多个门店，对应管理角色为店东。店东可能兼任
商圈经理，也可能聘请职业经理人担任商圈经理，因此“店东”和“圈经”不能无条件互换。

## 角色别名

| 说法 | 标准角色 | 说明 |
|---|---|---|
| 圈经 | 商圈经理 | 门店实际管理者 |
| CA、区域经理 | CA | CA区域负责人 |
| CAD、区域总监 | CAD | CA直属上级 |
| 大部总 | 运营总 | CAD直属上级 |
| 战区总 | 区域总 | 区域负责人 |
| BD | 拓展经理 | 负责外部门店加盟拓展 |
| BDD | 拓展总监 | BD直属上级 |
| CM | 渠道经理 | 推动外渠门店新房业务 |
| CMD | 渠道总监 | CM直属上级 |

# Notes

- 品牌组织架构在原文中标记为“待定”，本卡不补造该层级。
- 本卡描述业务管理语义；可执行组织编码仍以组织主数据和 `org/hierarchy` 为准。
