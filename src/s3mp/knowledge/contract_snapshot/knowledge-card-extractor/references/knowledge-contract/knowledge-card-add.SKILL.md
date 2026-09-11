---
name: knowledge-card-add
description: 在本仓库新增或修改知识卡片（指标 metric、表 table、业务概念 concept、数据管控 policy、归因 attribution、等式 equation、举措 action、组织/术语 org、工具 tool）或维护术语映射时使用。触发场景：加指标卡、新增表卡、建归因框架、加拆解等式、加概念消歧卡、加数据管控策略、加术语/黑话映射、改口径、新增受控词。
---

# 新增/修改知识卡片流程

## 前置阅读（每次执行前）

1. `schema/SCHEMA.md` —— 字段规范与正文约定章节
2. `ontology/vocabularies.yaml` —— 受控字段的合法取值
3. `ontology/schema.yaml` —— **本体机器可读事实源**：某个属性适用于哪些卡型、是否受控、
   是否必填、是否允许推导，以这份为准（SCHEMA.md 里带 `BEGIN GENERATED` 标记的表由它生成）
4. `index/index.yaml` —— 检查是否已存在同名/同义卡片

## 流程

### 1. 判型与查重

- 确定 type。判别参考：有口径公式→metric；描述数据表→table；解释"为什么/如何分析"的分层因子、方法和评价规则→attribution；指标间的加减乘除拆解→equation；"指标异动该做什么"→action；术语/组织/编码映射→org；外部系统/API 的接入说明（怎么调、input/output schema）→tool。
- **V2 新增两型，先判掉它们再考虑其余**：
  - **concept**——同一个业务词在不同分面下指向不同事实（"成交"在新房指认购、在二手指签约）。
    注意与另外两套机制的分工：**无条件的一对一映射用 `org/term-alias`**（"买卖"→二手）、
    **跨分面歧义用 concept**、**同名不同口径的指标族用 `variant_of`**。三者职责不重叠。
  - **policy**——数据管控规则（安全/权限/质量/生命周期）。判据是"这条知识回答的是
    *这是什么*（描述性）还是*能不能用*（约束性）"；约束性的一律进 policy，**不要标在表卡上**：
    `agent_name` 出现在 64 张表，逐表标注必然漂移。表卡只承载例外。
- 在 index.yaml 中查重：已有同义卡→改卡而非新建；**同名但口径不同→新建卡 + `variant_of` 指向既有卡**，禁止在旧卡里堆多口径。

### 2. 建卡

- metric：复制模板到 `knowledge/metric/<指标平台数字ID>.md`，`id` 必须为 `metric::<同一数字ID>`
- 其他类型：复制模板到 `knowledge/<type>/<kebab-name>.md`，`id` 必须为 `<type>/<kebab-name>`
- 非 metric 文件名使用英文 kebab-case；所有卡片的 `title` 使用中文业务名

### 3. 填 frontmatter

- 必填：type / id / title / resource / owner / updated_at
- `resource` 指向事实源并携带源系统 id（如 `metric-platform://metric::12345`、`warehouse://dw.fact_deal`，见 SCHEMA §1.5 / D17）。**metric/table 卡是薄投影**：canonical_name、formula、业务口径、字段清单以指标平台/数仓元数据为准，无权威来源时不编造，标 ⚠️ 待与源系统对齐
- metric 的 `canonical_name` 是可选 YAML 字段，只能原样填写源系统规范名；`business_definition` 是可选逻辑信息项，写入正文 `# Business Definition` 章节，不写 YAML。两者缺失均不阻断建卡，也不要求存量卡回填
- 受控字段（unit / business_line / topic / business_domain / dimensions / status / scope / provenance）取值**必须**在 vocabularies.yaml 词表内；dimensions 组织维度用规范名（大区、门店，不写"大区/大部"），业务维度（渠道等）不在白名单时走本体提案
- **判别属性（V2）**：table 卡的 `layer / time_grain / lifecycle / queryable / business_objects`、
  metric 卡的 `polarity / aggregation / time_semantics / metric_kind`。全部可选，缺失走推导不报错，
  但**新建卡应当显式声明**——健康度报告跟踪"显式声明率"，推导只兜底存量。
  - `business_objects` 用带 role 的写法：`- {object: 成交, role: 主对象}`。
    **主对象 = 这张表承载该对象（粒度键就是它）；关联对象 = 只是含有外键。**
    简写 `business_object: [成交]` 也合法，等价于声明主对象
  - `queryable` 非"可查"时 `query_note` 必填，写清原因与替代表
  - `aggregation: 半可加` 时 `semi_additive_along` 必填，说明沿哪些维度可加
  - 卡片显式声明**永远覆盖推导值**；不同意推导结果就在卡上写一行，不要去改代码
- 引用字段（depends_on / applies_to / factors / result / responds_to.metric / variant_of）只能填已存在的卡片 id，断链会被校验拦截；被引用卡不存在时先建它或询问用户
- 需要的受控词不在词表里时：**不得擅自往 vocabularies.yaml 加词**，这是本体提案，向用户说明并等确认
- `topic` 填写规则（词表 v1.2 正交化）：不得使用编码了业务线的主题词——填 `topic: [市场情况]` + `business_line: [二手]`，而不是 `topic: [二手市场情况]`；指标的主题归属以 `knowledge/org/topic-metrics.md` 为准，建 metric 卡前先查该表
- 应用专属 table / attribution / equation / action 卡必须显式填写 `application_scope`；缺失表示跨应用共享。请求范围只由 `appKey` 经 `mappings/application-scopes.yaml` 映射产生，不把应用判断写入 tags 或检索代码
- attribution 的 `evaluation_rules` 必须区分阈值、参考均值和连续趋势，并填写条件与依据；经验均值不得写成达标阈值，draft 规则不得驱动硬约束
- module 字段已废弃，不要使用

### 3.1 concept / policy 卡的专属要求

**concept**：`senses` 至少要能走通 `用户词 → sense → metric → table/column → codelist → predicate`
这条链——只写"这个词指哪个指标"不够，Agent 最终要把业务词翻译成 WHERE 条件。
缺绑定校验器会告警。`disambiguation: required` 表示用户未指明分面时 Agent **必须回问**，
不得自行选一个口径作答。

> 定位不到权威指标时，**`metrics` 留空并在 note 里标注"待业务确认"，不要猜一个填进去**。
> 猜错的后果是 Agent 用错误口径自信作答，比 miss 更糟。参考 `knowledge/concept/haofang.md`。

**policy**：`match` 必须**同时**给 `column_matches` 与 `meaning_matches`。只按字段名匹配会漏掉
最危险的一类——`customer_list` / `agent_list` / `customer_info_list` 这类 JSON 打包 PII 字段名里
没有任何敏感词，纯字段名匹配 100% 漏检。`exemptions` 的 `reason / approved_by / expires_at`
三项缺一校验器直接报错，过期豁免自动失效。

`severity × handling` 要组合着定，不能一刀切：客户手机号是 `禁止/不可见`，
经纪人姓名是 `提示/需授权`——后者若按客户 PII 同级禁止，"成都哪个经纪人做得好"这个
MVP 主场景会直接失效。

### 4. 填正文

按 SCHEMA.md 该 type 的约定章节写（如 metric 的 `# Definition` / 可选 `# Business Definition` / `# Examples`，table 的 `# Schema` / `# Join Path`）。metric 的 Definition 写指标说明，Business Definition 单独写统计对象、时间范围、纳入/排除条件、状态边界、去重规则等正式业务口径，二者不得混写。事实来源不明的内容不编造，留占位并标注 ⚠️ 待确认。

**attribution / equation / action 无外部事实源**（归因框架、拆解等式、举措是本知识库首创沉淀的资产），正文（Factors / Decomposition / Playbook）必须完整写出，不得只留 resource 指针。

### 5. 状态与来源标记（不可违反）

- `status: draft`——AI 产出的卡永远是 draft，reviewed 由 owner 人工流转
- `provenance`：AI 起草 → `ai_suggested`；从用户提供的文档提取 → `ai_extracted`，同时填 `source_ref` 指向原文

### 6. 校验（必做）

```bash
python3 scripts/build_index.py          # 校验 + 推导 + 索引 + 健康度
```

校验失败逐项修复后重跑；通过后 index.yaml 与 health.yaml 自动更新，不要手工改它们。

若本次改动**同时**碰了 `ontology/`、`mappings/` 或 `tools/`，还要跑：

```bash
python3 scripts/check_no_hardcode.py         # 防漂移
python3 scripts/gen_projections.py --check   # 三端投影与本体一致
python3 -m pytest tests/ -q                  # 检索层契约回归
```

### 7. 汇报

向用户报告：新卡 id、引用了哪些卡（边）、校验结果、提醒"owner 审核通过后将 status 改为 reviewed"。

补充说明发布语义，避免误解：**draft 卡可以被检索到、也会进知识包**（否则全量零 reviewed 时
知识能力直接清零），返回时带 `agent_note` 要求 Agent 标注"未经确认"；
但 draft **不能驱动硬剪枝、policy 或默认口径**这类高影响判断。

## 术语/词表类改动的特殊规则

- 加黑话/别名映射：改 `knowledge/org/term-alias.md` 的 Mapping 表，属实例层，正常走流程
- **加业务对象词 / 粒度意图词 / 时间粒度词 / 方向词 / 城市识别排除词**：同样改
  `knowledge/org/term-alias.md` 的对应章节。这些是 V2 从检索器代码里搬出来的词表，
  **检索器现在直接读卡，改完重启即生效**
- 加城市编码/组织节点：改 `knowledge/org/hierarchy.md`
- 跨表复用的枚举（如合同状态码）：抽成 `knowledge/org/codelist-*` 卡，表卡 Schema 表格
  第 5 列填该卡 id，**不要在表卡里展开枚举值**——各抄各的必然漂移
- 改主题/裸词的指标展开清单：改 `knowledge/org/topic-metrics.md` 卡本身。
  ⚠️ **V2 起事实源是卡，不是 json**：`参考资料/*.json` 已降级为一次性导入材料，
  检索器只用它补卡里没有的条目，**绝不覆盖卡片已声明的值**。
  （v1.0 的实现是"json 存在就永远不读卡"，导致改了卡、跑了校验、合了代码却运行时不生效）
- 改推导规则（表名/字段名 → 判别属性）：改 `mappings/derivations.yaml`。
  **这不是本体**，是源系统接入映射，随数仓命名规范走；每条规则必须带 `review_due`
- 改打分权重、预算、top_k：改 `config/retrieval.yaml`。**不要改代码，也不要写进本体**——
  它们不改变任何业务事实，只改变排序偏好
- 加 unit / business_line / topic / business_object 等词表值、加边类型、加判别属性、
  新增裸词展开入口：**本体提案**，必须用户确认后才能改 `ontology/` 下文件。
  新主题词必须正交（业务线/业态信息走各自分面，不编进主题词）
- **把某个判别属性从加权升级为硬剪枝**：覆盖率达标只是必要条件，还须
  `precision_verified` + `prune_approved`（owner 显式批准），**绝不因覆盖率达标自动切换**
