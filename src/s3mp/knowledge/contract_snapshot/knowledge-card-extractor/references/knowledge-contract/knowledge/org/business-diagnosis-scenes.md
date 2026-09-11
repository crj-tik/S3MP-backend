---
type: org
id: org/business-diagnosis-scenes
title: 业务诊断场景路由表
description: 业务诊断场景 scene_key、project_code、analysis_object 与适用对象类型的映射
resource: ../../参考资料/business-diagnosis-router/config/diagnosis_scenes.json
owner: 大数据中心（待业务专家确认）
updated_at: 2026-07-16
status: draft
scope: enterprise
provenance: ai_extracted
source_system: 业务诊断树 API
source_ref: ../../参考资料/business-diagnosis-router/config/diagnosis_scenes.json
unit: [经纪]
business_line: [二手, 新房, 租赁]
tags: [诊断, 场景, 路由]
---

> 本卡由 business-diagnosis-router Skill 的 `diagnosis_scenes.json` 提取。改诊断场景时应先改源配置，再重建本卡。

# Mapping

## 场景清单

| scene_key | 场景 | 适用对象 | project_code | analysis_object | 说明 |
|---|---|---|---|---|---|
| business_diagnosis_area_ca_circle | 业绩诊断 | 大区/CA/商圈 | 520 | area_code | 用于分析大区/CA/商圈的业务诊断概要，用于概括性地描述哪些业务板块做得好，哪些业务板块做得不好 |
| business_diagnosis_area | 业绩诊断 | 大区 | 430 | area_code | 用于分析大区的业务诊断概要，用于概括性地描述哪些业务板块做得好，哪些业务板块做得不好 |
| business_diagnosis_ca | 业绩诊断 | CA | 428 | shop_director_code | 用于分析CA的业务诊断概要，用于概括性地描述哪些业务板块做得好，哪些业务板块做得不好 |
| business_diagnosis_shop | 业绩诊断 | 门店 | 390 | shop_code | 用于分析门店的业务诊断得分模型，用于概括性地描述哪些业务板块做得好，哪些业务板块做得不好 |
| business_diagnosis_shop_443 | 业绩诊断 | 门店 | 443 | shop_code | -- |
| business_result_shop | 经营结果 | 门店 | 391 | shop_code | 用于分析门店的业绩表现，二手、新房、租赁的整体表现，一二手业绩结构是否合理 |
| house_management_area_ca_circle | 房源管理 | 大区/CA/商圈 | 419 | area_code | 用于分析大区/CA/商圈的二手房源管理情况，定位做得好和做得不好的子业务板块是哪些 |
| house_management_shop | 房源管理 | 门店 | 398 | shop_code | 用于分析门店的二手房源管理情况，定位做得好和做得不好的子业务板块是哪些 |
| customer_management_area_ca_circle | 客源管理 | 大区/CA/商圈 | 420 | area_code | 用于分析大区/CA/商圈的二手客源管理情况，定位做得好和做得不好的子业务板块是哪些 |
| customer_management_shop | 客源管理 | 门店 | 397 | shop_code | 用于分析门店的二手客源管理情况，定位做得好和做得不好的子业务板块是哪些 |
| opportunity_management_area_ca_circle | 商机管理 | 大区/CA/商圈 | 421 | area_code | 用于分析大区/CA/商圈的二手商机管理情况，定位做得好和做得不好的子业务板块是哪些 |
| opportunity_management_shop | 商机管理 | 门店 | 399 | shop_code | 用于分析门店的二手商机管理情况，定位做得好和做得不好的子业务板块是哪些 |
| people_management_area_ca_circle | 人员管理 | 大区/CA/商圈 | 422 | area_code | 用于分析大区/CA/商圈的人员管理情况，定位做得好和做得不好的子业务板块是哪些 |
| people_management_shop | 人员管理 | 门店 | 396 | shop_code | 用于分析门店的人员管理情况，定位做得好和做得不好的子业务板块是哪些 |
| new_house_business_area_ca_circle | 新房业务 | 大区/CA/商圈 | 423 | area_code | 用于分析大区/CA/商圈的新房业务情况，定位做得好和做得不好的子业务板块是哪些 |
| new_house_business_shop | 新房业务 | 门店 | 393 | shop_code | 用于分析门店的新房业务情况，定位做得好和做得不好的子业务板块是哪些 |
| second_hand_index_area_ca_circle | 二手行指 | 大区/CA/商圈 | 434 | area_code | 用于分析大区/CA/商圈的二手行指情况，定位做得好和做得不好的子业务板块是哪些 |
| second_hand_market_change_area_ca_circle | 二手市场变化 | 大区/CA/商圈 | 427 | area_code | 用于分析大区/CA/商圈的二手市场情况，描述二手市场的成交量价、成交结构、供需关系、客业主预期等 |
| other_sign_ca_shop | 我客他签 | CA/门店 | 594 | shop_director_code | 用于分析CA/门店的我客他签情况，分析每个客户丢客的原因复盘 |
| good_house_improvement_ca_shop | 优良房提升 | CA/门店 | 583 | shop_director_code | 用于分析CA/门店的二手房源维护情况，定位到每个套房的具体维护动作有哪些，应该怎么提升 |
| other_showing_ca_shop | 我客他带 | CA/门店 | 608 | shop_director_code | 用于分析CA/门店的我客他带情况，分析每个客户他带的原因复盘 |
| opportunity_loss_order | 商机损单 | 门店/经纪人/商机id | 631 | shop_code | 用于分析CA/门店的商机损单情况，分析每个商机被他签的情况 |

## 路由建议

| 用户意图 | 对象类型 | 推荐 scene_key |
|---|---|---|
| 业绩诊断、整体表现 | 大区/CA/商圈 | business_diagnosis_area_ca_circle |
| 业绩诊断、整体表现 | 大区 | business_diagnosis_area |
| 业绩诊断、整体表现 | CA | business_diagnosis_ca |
| 业绩诊断、整体表现 | 门店 | business_diagnosis_shop |
| 经营结果、业绩表现 | 门店 | business_result_shop |
| 房源管理、房源维护 | 大区/CA/商圈 | house_management_area_ca_circle |
| 房源管理、房源维护 | 门店 | house_management_shop |
| 客源管理、客户跟进 | 大区/CA/商圈 | customer_management_area_ca_circle |
| 客源管理、客户跟进 | 门店 | customer_management_shop |
| 商机管理、成交转化 | 大区/CA/商圈 | opportunity_management_area_ca_circle |
| 商机管理、成交转化 | 门店 | opportunity_management_shop |
| 人员管理、人效 | 大区/CA/商圈 | people_management_area_ca_circle |
| 人员管理、人效 | 门店 | people_management_shop |
| 新房业务 | 大区/CA/商圈 | new_house_business_area_ca_circle |
| 新房业务 | 门店 | new_house_business_shop |
| 二手行指 | 大区/CA/商圈 | second_hand_index_area_ca_circle |
| 二手市场变化 | 大区/CA/商圈 | second_hand_market_change_area_ca_circle |
| 我客他签、丢客 | CA/门店 | other_sign_ca_shop |
| 优良房、房源维护 | CA/门店 | good_house_improvement_ca_shop |
| 我客他带 | CA/门店 | other_showing_ca_shop |
| 商机损单 | 门店/经纪人/商机id | opportunity_loss_order |

# Notes

- `analysis_object=shop_code` 表示按门店编码调用。
- `analysis_object=area_code` 表示按大区/CA/商圈类组织编码调用。
- `analysis_object=shop_director_code` 常用于 CA 或 CA/门店混合场景，调用前应结合组织解析结果确认对象编码。
- 用户未明确诊断场景时，默认回退到对象类型对应的“业绩诊断”场景。
