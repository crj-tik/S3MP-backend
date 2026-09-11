# 知识卡片 Schema 规范

- 版本：v2.0-draft
- 事实源：[../ontology/schema.yaml](../ontology/schema.yaml)。**本文是它的人读投影**——
  带 `BEGIN GENERATED` 标记的片段由 `scripts/gen_projections.py` 生成，不要手改；
  其余解释性文字人工维护
- 依据：[02-技术方案文档](../docs/02-技术方案文档.md) §4、§5、[docs/本体V2](../docs/本体V2/)
- 消费原则：**渐进式披露、宽松消费**——未知字段、断链不视为错误，消费方容错。
  **唯一例外是 policy 卡**：约束性知识在不确定时 fail-closed，见 §5
- 模板：[templates/](./templates/)，新建卡片从对应模板复制

## 1. 通用结构

每张卡片是一个 UTF-8 Markdown 文件：YAML frontmatter + 正文。

### 1.1 命名与存放约定

- `id` 全局唯一。metric 使用指标平台 ID：`metric::<数字ID>`，如 `metric::25713`；文件存放于 `knowledge/metric/<数字ID>.md`
- 其他类型继续使用路径式命名 `<type>/<kebab-case-name>`，文件存放于 `knowledge/<type>/<kebab-case-name>.md`
- `title` 用中文业务名称
- **id 与语义的分工**：id 是稳定标识，不承担语义与检索职责（命中靠 title/canonical_name/description/tags/术语表）；业务改名只改 title，id 永不变更，保证引用边不断。命名规则：业务专名用拼音（ershou、daikan），通用词用英文（count、rate、perf）；不用中文文件名（跨平台 Unicode 规范化风险）

### 1.2 必填字段（所有 type）

```yaml
type: metric | table | concept | policy | attribution | equation | action | org | tool
id: string          # 全局唯一；metric::数字ID，或其他类型的 <type>/<kebab-case-name>
title: string       # 中文业务名称
resource: uri       # 真实内容/数据所在位置指针（如 warehouse://dw.fact_deal）
owner: string       # 维护方
updated_at: date
```

### 1.3 推荐字段（所有 type）

```yaml
description: string
unit: [string]            # 受控词表：经纪 | 整装 | 贝好家（→ in_unit 边）
business_line: [string]   # 受控词表，按业态（→ in_line 边）
business_domain: [string] # 受控词表，按业务域：北京链家 | 贝壳城市 | 通用
topic: [string]           # 受控词表，可多值（→ in_topic 边）
tags: [string]            # 自由标签，仅检索召回，不进图谱
ai_tags: [string]         # 模型批量生成，可随时重刷，仅扩大召回
status: draft | reviewed | deprecated     # 默认 draft
scope: enterprise | team | personal       # 默认 enterprise
provenance: human | ai_extracted | ai_suggested   # 默认 human
source_ref: uri           # 提取类知识指向原始文档，溯源用
```

> `module` 字段自 v2.0 **正式废弃**（v0.4 起被三级分面取代）。卡片中出现该字段校验器直接报错。

受控词表取值见 [../ontology/vocabularies.yaml](../ontology/vocabularies.yaml)。

### 1.4 标签使用规则（红线）

- 结构关系一律用受控字段/分类型扩展字段表达，**禁止用 tags 表达关系**
- 同义词/别名**不进 tags**，统一维护在 org 术语卡（alias_of），供 query 归一化

### 1.5 resource 与事实源约定（D17）

- `resource` 指向该知识的**事实源**，URI 约定：scheme 标识源系统、路径携带源系统内的唯一 id，如 `metric-platform://metric::12345`、`warehouse://dw.fact_deal`——这是卡片 id ↔ 源系统 id 打通的载体
- **metric / table 卡是薄投影**：卡内 formula、字段清单为源系统的投影，事实源以指标平台/数仓元数据为准；分面、关系边、default、dimensions 等检索推理层字段必须在卡内维护（源系统没有）
- **attribution / equation / action 卡的事实源就是卡片本身**：正文必须完整，`resource` 指向本文件，不得只留指针

## 2. 分类型扩展字段

### type: table

```yaml
schema_ref: uri        # 实际字段定义所在（数仓元数据/DDL）
refresh_freq: string
```

表卡推荐填写 `business_domain`，用于区分北京链家、贝壳城市或通用维表/公共表；同一表可多值，但只在确有跨域复用时使用 `通用` 或多值。

应用专属表必须显式填写 `application_scope`。缺失表示跨应用共享；请求侧取值只能由
`appKey` 经 `mappings/application-scopes.yaml` 映射产生，不接受 Agent 在 facets 中直接填写。

正文约定章节：`# Schema`（字段列表及含义）、`# Join Path`（与其他表的关联，用链接指向对应卡片，join keys 写明）。

### type: metric

```yaml
canonical_name: string      # 可选；源系统中的指标规范名称，须原样保存，如“纯新签单量*COO二手买卖*贝联_月”
formula: string
value_continuity: 离散 | 连续  # 可选；指导评价方法，不参与硬过滤
dimensions: [string]      # 维度下钻能力，受控词表 vocabularies.dimensions（组织/时间/业务三组）；长期为指标平台同步投影（D17）
default: boolean          # 是否默认口径，多口径场景用
depends_on: [concept_id]  # 依赖的 table（→ depends_on 边）
variant_of: concept_id    # 指标族口径变体（→ variant_of 边，D10）
```

`canonical_name` 是可选的源系统规范名，不等同于面向人的 `title`，也不承担稳定标识职责（稳定标识仍是 `id`）。仅在能从指标平台等权威来源确认时填写；不得根据标题猜造。

metric 正文约定以下章节：

metric 卡推荐填写 `business_domain`，用于区分北京链家、贝壳城市或通用指标；`business_domain` 表示组织/经营业务域，`business_line` 仍只表示二手/新房/租赁等业态。

- `# Definition`：指标说明。解释指标衡量什么、业务意义、适用分析场景，以及多口径差异原因。
- `# Business Definition`：可选的业务口径长文本。记录统计对象、统计事件、时间范围、纳入/排除条件、有效状态、去重规则、统计粒度和特殊边界；有权威来源时原意投影，不把 SQL/公式重复粘贴到这里。
- `# Examples`：典型查询示例。

> `business_definition` 是 metric 的逻辑信息项，但物理上存放于 Markdown 的 `# Business Definition` 章节，**不写入 YAML frontmatter**。这样既适合长文本阅读，也避免与正文双写。该章节与 `canonical_name` 均为可选，存量卡不要求回填，缺失不影响校验。

### type: attribution

```yaml
applies_to: [concept_id]  # 适用的指标，可多个（→ 反向派生 attributed_by 边）
factors: [concept_id]     # 归因因子，指向 metric/table（→ factor_of 边）
analysis_methods: [趋势, 同比, 环比]
evaluation_rules:         # 带业务线/组织层级条件的阈值、均值或连续趋势
  - {metric: concept_id, rule_type: 阈值, operator: 大于等于,
     value: 0.5, value_unit: 比例, when: {scope_level: [城市]}, basis: 业务标准}
reviewed_by: string
```

正文约定章节：`# Factors`（因子列表及逻辑）、`# Analysis Method`（分析步骤与前提）、
`# Evaluation Rules`（阈值/均值的解释和误用边界）、`# Citations`（依据来源）。

应用专属归因框架、等式和举措可填写 `application_scope`。`appKey` 命中时仅软加权；
未标记的共享分析知识继续参与召回，draft 评价规则不能驱动硬约束。

### type: equation

```yaml
result: concept_id                    # 等式左边（→ result 边；反向派生 has_equation）
factors:                              # 等式右边（→ factor 边）
  - { id: concept_id, role: 量 | 率 | 价 | 分子 | 分母 | 被减数 | 减数 }
operator: 乘法 | 加法 | 除法 | 减法
```

正文约定章节：`# Decomposition`（拆解逻辑、适用分析视角）、`# Priority`（因子排查优先级）。

四则指标等式统一用 equation 表达（operator 区分）；一个指标可挂多套拆解（管理/作业视角），互不干扰。

### type: action

```yaml
responds_to:                          # 触发条件（→ 反向派生 responds_with 边）
  - { metric: concept_id, condition: 上升 | 下降, threshold: string }
owner_role: string                    # 执行责任方（如 门店店长）
```

正文约定章节：`# Playbook`（具体做什么）、`# Applicability`（适用范围与前提）。

### type: org

```yaml
source_system: string   # 指向的原系统（CRM/HR/取数工具）
```

正文约定章节：`# Mapping`（名称→编码映射、alias_of 别名映射、层级定义）。

### type: tool

```yaml
input_schema: object
output_schema: object
invocation: string       # 调用方式说明
```

## 3. 判别属性（V2 新增）

分面回答"属于谁"，**判别回答"能不能用"**。两者区别是硬性的：分面值变了不影响这条知识
对不对；判别值变了会**直接改变 Agent 的行为**（`queryable: 不可查` 的表不该被推荐去 join，
`polarity: 逆向` 的指标上升是坏消息）。

v1.0 只有分面没有判别，判别逻辑于是沉到检索器的 330 行硬编码里——
**判别在代码里 → 本体填了也没用 → 更没人填**，这是分面填写率 0% 的根因。

<!-- BEGIN GENERATED: discriminants -->

| 属性 | 适用卡型 | 受控词表 | 取值 | 生效档位 |
|---|---|---|---|---|
| `aggregation` | metric | `metric_aggregation` | 不可加、半可加、可加 | False |
| `ambiguous` | concept | `—` | — | off |
| `business_objects` | table | `—` | — | weight |
| `default` | metric | `—` | — | weight |
| `disambiguation` | concept | `concept_disambiguation` | default、none、required | off |
| `handling` | policy | `policy_handling` | 不可见、可见不可查、需授权、需脱敏 | off |
| `layer` | table | `table_layer` | 临时、指标表、明细、汇总、维表 | weight |
| `lifecycle` | table、metric | `lifecycle` | 下线中、已下线、测试、生产 | prune |
| `metric_kind` | metric | `metric_kind` | 原子、复合、派生 | weight |
| `polarity` | metric | `metric_polarity` | 中性、正向、逆向 | weight |
| `policy_kind` | policy | `policy_kind` | 安全、权限、生命周期、质量 | off |
| `queryable` | table | `queryable` | 不可查、受限、可查 | weight |
| `scope_level` | attribution、action | `scope_level` | CA、业城、事业部、加盟商、区域、商圈、地城、城市、大区、大部、店组、经纪人、贝壳城市、赋能区域、门店 | off |
| `severity` | policy | `policy_severity` | 受限、提示、禁止 | off |
| `time_grain` | table | `time_grain` | 周、实时、小时、无时间、日、月 | weight |
| `time_semantics` | metric | `metric_time_semantics` | 时段、时点、累计 | False |
| `value_continuity` | metric | `value_continuity` | 离散、连续 | False |

<!-- END GENERATED: discriminants -->

全部可选。缺失 = 未标注，走推导规则或降权，**不报错**——存量 1364 张卡零回填。
新建卡片建议显式声明：显式声明率是健康度报告的跟踪项，推导依赖度应随时间下降。

### 3.1 business_objects 的两级模型

```yaml
business_objects:
  - {object: 成交, role: 主对象, evidence: unique_key}     # 证据是粒度键，精确
  - {object: 门店, role: 关联对象, evidence: has_column}    # 证据是字段存在，宽松
```

简写 `business_object: [成交]` 仍然合法，视为**人工显式声明的主对象**。

两级不是设计洁癖，是实测结论：`has_column: shop_code` 让"门店"命中 85/173 张表（49%），
但绝大多数表只是**含有**门店外键，并不**承载**门店这个对象。因此
**主对象可用于剪枝，关联对象永久只加权**。

## 4. 分类型字段清单（由本体生成）

<!-- BEGIN GENERATED: type_fields -->

### type: metric

| 字段 | 类别 | 取值 | 必填 |
|---|---|---|---|
| `canonical_name` | descriptive | string | 否 |
| `formula` | descriptive | string | 否 |
| `semi_additive_along` | descriptive | object | 条件：{'aggregation': ['半可加']} |
| `aggregation` | discriminant | 受控 `metric_aggregation` | 否 |
| `default` | discriminant | boolean | 条件：{'_has_same_name_variant': True} |
| `lifecycle` | discriminant | 受控 `lifecycle` | 否 |
| `metric_kind` | discriminant | 受控 `metric_kind` | 否 |
| `polarity` | discriminant | 受控 `metric_polarity` | 否 |
| `time_semantics` | discriminant | 受控 `metric_time_semantics` | 否 |
| `value_continuity` | discriminant | 受控 `value_continuity` | 否 |
| `business_domain` | facet | 受控 `business_domain`（多值） | 否 |
| `business_line` | facet | 受控 `business_line`（多值） | 否 |
| `dimensions` | facet | 受控 `dimensions`（多值） | 否 |
| `topic` | facet | 受控 `topic`（多值） | 否 |
| `unit` | facet | 受控 `unit`（多值） | 否 |
| `depends_on` | relation | ref_list（多值） | 否 |
| `derived_from` | relation | ref_list（多值） | 否 |
| `variant_of` | relation | ref | 条件：{'_has_same_name_variant': True} |

### type: table

| 字段 | 类别 | 取值 | 必填 |
|---|---|---|---|
| `query_note` | descriptive | string | 条件：{'queryable': ['不可查', '受限']} |
| `refresh_freq` | descriptive | string | 否 |
| `schema_ref` | descriptive | string | 否 |
| `unique_key` | descriptive | nested_list（多值） | 否 |
| `business_objects` | discriminant | object_list（多值） | 否 |
| `layer` | discriminant | 受控 `table_layer` | 否 |
| `lifecycle` | discriminant | 受控 `lifecycle` | 否 |
| `queryable` | discriminant | 受控 `queryable` | 否 |
| `time_grain` | discriminant | 受控 `time_grain`（多值） | 否 |
| `application_scope` | facet | 受控 `application_scope`（多值） | 否 |
| `business_domain` | facet | 受控 `business_domain`（多值） | 否 |
| `business_line` | facet | 受控 `business_line`（多值） | 否 |
| `unit` | facet | 受控 `unit`（多值） | 否 |

### type: concept

| 字段 | 类别 | 取值 | 必填 |
|---|---|---|---|
| `default_sense` | descriptive | string | 条件：{'disambiguation': ['default']} |
| `ambiguous` | discriminant | boolean | 否 |
| `disambiguation` | discriminant | 受控 `concept_disambiguation` | 否 |
| `business_domain` | facet | 受控 `business_domain`（多值） | 否 |
| `business_line` | facet | 受控 `business_line`（多值） | 否 |
| `topic` | facet | 受控 `topic`（多值） | 否 |
| `unit` | facet | 受控 `unit`（多值） | 否 |
| `senses` | relation | object_list（多值） | 否 |

### type: policy

| 字段 | 类别 | 取值 | 必填 |
|---|---|---|---|
| `handling` | discriminant | 受控 `policy_handling` | 是 |
| `policy_kind` | discriminant | 受控 `policy_kind` | 是 |
| `severity` | discriminant | 受控 `policy_severity` | 是 |
| `agent_message` | governance | string | 是 |
| `exemptions` | governance | object_list（多值） | 否 |
| `legal_basis` | governance | string | 是 |
| `masking` | governance | string | 条件：{'handling': ['需脱敏']} |
| `match` | governance | object | 是 |

### type: attribution

| 字段 | 类别 | 取值 | 必填 |
|---|---|---|---|
| `analysis_methods` | descriptive | 受控 `analysis_method`（多值） | 否 |
| `evaluation_rules` | descriptive | object_list（多值） | 否 |
| `scope_level` | discriminant | 受控 `scope_level`（多值） | 否 |
| `application_scope` | facet | 受控 `application_scope`（多值） | 否 |
| `business_domain` | facet | 受控 `business_domain`（多值） | 否 |
| `business_line` | facet | 受控 `business_line`（多值） | 否 |
| `topic` | facet | 受控 `topic`（多值） | 否 |
| `unit` | facet | 受控 `unit`（多值） | 否 |
| `reviewed_by` | governance | string | 否 |
| `applies_to` | relation | ref_list（多值） | 否 |
| `factors` | relation | ref_list（多值） | 否 |

### type: equation

| 字段 | 类别 | 取值 | 必填 |
|---|---|---|---|
| `operator` | descriptive | 受控 `equation_operator` | 否 |
| `application_scope` | facet | 受控 `application_scope`（多值） | 否 |
| `business_domain` | facet | 受控 `business_domain`（多值） | 否 |
| `business_line` | facet | 受控 `business_line`（多值） | 否 |
| `topic` | facet | 受控 `topic`（多值） | 否 |
| `unit` | facet | 受控 `unit`（多值） | 否 |
| `factors` | relation | ref_list（多值） | 否 |
| `result` | relation | ref | 否 |

### type: action

| 字段 | 类别 | 取值 | 必填 |
|---|---|---|---|
| `owner_role` | descriptive | string | 否 |
| `scope_level` | discriminant | 受控 `scope_level`（多值） | 否 |
| `application_scope` | facet | 受控 `application_scope`（多值） | 否 |
| `business_domain` | facet | 受控 `business_domain`（多值） | 否 |
| `business_line` | facet | 受控 `business_line`（多值） | 否 |
| `topic` | facet | 受控 `topic`（多值） | 否 |
| `unit` | facet | 受控 `unit`（多值） | 否 |
| `responds_to` | relation | object_list（多值） | 否 |

### type: org

| 字段 | 类别 | 取值 | 必填 |
|---|---|---|---|
| `source_system` | descriptive | string | 否 |
| `business_domain` | facet | 受控 `business_domain`（多值） | 否 |
| `business_line` | facet | 受控 `business_line`（多值） | 否 |
| `unit` | facet | 受控 `unit`（多值） | 否 |

### type: tool

| 字段 | 类别 | 取值 | 必填 |
|---|---|---|---|
| `input_schema` | descriptive | object | 否 |
| `invocation` | descriptive | string | 否 |
| `output_schema` | descriptive | object | 否 |
| `business_domain` | facet | 受控 `business_domain`（多值） | 否 |
| `business_line` | facet | 受控 `business_line`（多值） | 否 |
| `unit` | facet | 受控 `unit`（多值） | 否 |


<!-- END GENERATED: type_fields -->

## 5. 生命周期与发布语义

```
draft ──owner 审核──▶ reviewed ──▶ (过期/被替代) deprecated
```

- 三条入口（人工手写 / Agent 反馈生成 / 文档提取）全部走此唯一闸门（D12）
- AI 只能产出 `provenance: ai_extracted|ai_suggested` 的 draft——**有提议权，没有落笔权**

v1.0 写的是"reviewed 后自动追加索引记录"，但实现把全部 draft 卡写进索引、检索器也不按
status 过滤——三处语义不一致。V2 把"发布"拆成四种能力，一次性定死：

<!-- BEGIN GENERATED: release_semantics -->

| status | 可被 search 发现 | 可进知识包 | 可作为最终事实 | 可驱动硬约束 |
|---|---|---|---|---|
| `draft` | ✓ | ✓ | ✗ | ✗ |
| `reviewed` | ✓ | ✓ | ✓ | ✓ |
| `deprecated` | ✓ | ✗ | ✗ | ✗ |

<!-- END GENERATED: release_semantics -->

关键取舍：**draft 可发现、可召回**（否则全量零 reviewed 时知识能力直接清零），
**但绝不可驱动硬约束**——硬剪枝、policy、默认口径这类高影响判断必须由人工审核过的知识驱动。
draft 卡返回时带 `agent_note`，要求 Agent 标注"未经确认"。

## 6. 关系边（由本体生成）

<!-- BEGIN GENERATED: edges -->

| 边 | 从 → 到 | 声明处 | 派生 | 跳数上限 |
|---|---|---|---|---|
| `in_unit` | metric、table → unit | `unit` | forward | — |
| `in_line` | metric、table → business_line | `business_line` | forward | — |
| `in_topic` | metric → topic | `topic` | forward | — |
| `depends_on` | metric → table | `depends_on` | forward | 1 |
| `derived_from` | metric → metric | `derived_from` | forward | 1 |
| `join_with` | table → table | `# Join Path` | forward | — |
| `has_equation` | metric → equation | `result` | reverse | — |
| `factor` | equation → metric | `factors` | forward | — |
| `result` | equation → metric | `result` | forward | — |
| `attributed_by` | metric → attribution | `applies_to` | reverse | — |
| `factor_of` | attribution → metric、table、attribution | `factors` | forward | 3 |
| `responds_with` | metric → action | `responds_to` | reverse | — |
| `variant_of` | metric → metric | `variant_of` | forward | — |
| `alias_of` | org → * | `# Mapping` | forward | — |
| `means_in` | concept → metric | `senses` | forward | — |
| `carries` | table → business_object | `business_objects` | forward | — |

<!-- END GENERATED: edges -->

`depends_on` 在 v1.0 实例中混写了 metric→table(1717) 与 metric→metric(1494)，
导致依赖闭包最大 66 张卡、知识包被预算截满。V2 由 `build_index.py` 按目标卡片 type
**自动分流**为 `depends_on` / `derived_from`，各自设跳数上限，**存量卡一行不改**。
