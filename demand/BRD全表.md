
# 语言交互大模型需求说明书（BRD）

> **文档日期**：2026-01-23

## 1. 文档信息

* 文档名称：语言交互大模型后处理业务需求说明书
* 适用范围：语音/文本自然语言交互 → 意图/槽位/实体标准化 → 设备/服务执行

---

## 2. 背景与问题


---

## 3. 目标与非目标

### 3.1 目标（本期必须）

1. **表驱动标准化**：根据配置表将意图、槽位、实体输出为标准值（canonical）
2. **合法性校验**：枚举、范围、必选槽位、能力支持必须校验；不通过则回退/澄清/拒绝
3. **能力矩阵 gating**：按设备类型判断某意图是否支持
4. **澄清（Need Clarify）闭环**：当缺槽/歧义/不支持时，输出可用于澄清的结构化原因与候选
5. **可追溯 trace**：输出包含命中规则、归一化、回退/阻断原因、配置版本信息

### 3.2 非目标（本期不强制）

* 不要求一次性实现复杂对话策略与话术（由对话层承接）
* 不要求一次性把 General 表升级为“逐条 code/alias/fallback/region”的新结构（先兼容现有格式）

---

## 4. 术语与对象

* **Intent（意图）**：用户要做的事，按 L1/L2/L3 分层（来自 IntentDefinitions.xlsx）
* **Slot（槽位）**：意图参数（如 power、brightness、temperature、location、scope 等）（来自 SlotDefinitions.xlsx）
* **Entity（实体）**：设备/位置/场景名称等（来自 Lexicon-*.xlsx）
* **Capability（能力矩阵）**：某设备类型支持哪些 intent_L1（来自 CapabilityMatrix.xlsx）
* **Canonical（标准值）**：配置表中定义的唯一标准取值（General/Lexicon/Slot enum）

---

## 5. 输入与输出（业务契约）——待研发补充

### 5.1 输入（后处理必须接收的最小信息）

* `user_text`：用户原始文本（或 ASR 文本）
* `locale`：语言/地区（可缺省）
* `llm_candidates`：大模型输出的候选意图/槽位/实体（可为一组候选）
* `device_context`（可选但强烈建议）：

  * 当前房间/默认位置
  * 可控设备清单（含 device_type）
  * 当前焦点设备（若有）

### 5.2 输出（后处理对下游的稳定承诺）

* `final_intent`：唯一意图（L1/L2/L3 + ID）
* `final_slots`：通过校验与归一化的槽位集合
* `resolved_entities`：设备/位置/场景等实体的 canonical
* `action`（可选）：归一化后的动作（来自 Lexicon-Action）
* `result_type`：`execute | need_clarify | reject`
* `decision_trace`：可解释信息（命中规则、归一化、回退/阻断原因、配置版本）

---

## 6 统一识别原因码（Reason Codes）

本节定义后处理对外输出的统一原因码，用于：**澄清（need_clarify）**、**拒绝（reject）**、以及 **trace 可回溯**。

| reason_code | 含义 | result_type | 后处理输出要求 |
| --- | --- | --- | --- |
| missing_required_slot | 缺少必选槽位（required） | need_clarify | clarify_slot=缺失字段；可附 candidates |
| invalid_enum | 枚举值不在 General/Slot enum 集合内 | need_clarify/reject | 若可回退则 fallback；否则 block，并写 enum_validation |
| out_of_range_clamped | 数值越界已 clamp | execute | trace 标记 clamp（slot_validation.result=clamped） |
| capability_unsupported | 能力矩阵不支持该 intent_L1 | need_clarify/reject | 返回 supported_intents 或建议换对象/换说法 |
| ambiguous_entity | 实体歧义（多个设备/位置/场景命中） | need_clarify | 返回候选列表 candidates（含 canonical 与 display） |
| entity_not_found | 未找到目标实体 | need_clarify | 提示用户指定设备/位置/场景；clarify_slot=device_name/location/scene_name |
| locale_missing_defaulted | locale 缺失已走默认策略 | execute | trace 标记 defaulted，写明来源 device/session/default |
| intent_conflict | 多意图冲突无法裁决 | need_clarify | 返回候选意图列表 candidates，并给 prompt_key |
| low_confidence | 模型/规则置信度不足 | need_clarify | 进入澄清或二次确认；返回候选与原因 |
| risky_action_need_confirm | 触发风控红线需二次确认 | need_clarify | 返回 confirm_action + summary（对象/范围/参数） |
| parse_time_failed | 时间表达无法解析 | need_clarify | clarify_slot=time；返回可解析格式示例 |
| parse_duration_failed | 时长表达无法解析 | need_clarify | clarify_slot=duration；返回可解析格式示例 |
| device_unavailable | 目标设备不可用（离线/无权限/不在清单） | need_clarify/reject | 返回 device_id/device_name 与不可用原因 |
| out_of_scope | 请求超出当前产品能力范围 | reject | 返回 reason_code=out_of_scope + 可用能力提示（可选） |

约定：
- `result_type=need_clarify` 时，必须输出 `reason_code`；并尽可能输出 `clarify_slot` 与 `candidates`。
- `result_type=reject` 时，必须输出 `reason_code` 与 `reason`（可读说明）。
- 所有原因码均需写入 `decision_trace`，便于线上排障与统计。

## 6.1 NeedClarify 机制（reason_code 标准）

本节定义后处理输出 `result_type=need_clarify` 时的**统一机制与字段标准**，确保对话层/前端能够一致地发起澄清、二次确认，并支持可观测统计。


### 6.1.1 触发条件（何时进入 need_clarify）

当且仅当满足以下任一条件时，后处理输出 `result_type=need_clarify`：

- **缺少必选槽位**：命中 `missing_required_slot`

- **实体歧义或缺失**：命中 `ambiguous_entity` / `entity_not_found`

- **意图冲突不可裁决**：命中 `intent_conflict`

- **能力矩阵不支持**：命中 `capability_unsupported`（也可在产品策略下转 reject）

- **高风险操作需确认**：命中 `risky_action_need_confirm`

- **时间/时长解析失败**：命中 `parse_time_failed` / `parse_duration_failed`

- **置信度不足**：命中 `low_confidence`

- **设备不可用**：命中 `device_unavailable`（也可在产品策略下转 reject）


### 6.1.2 输出字段规范（对话层可直接消费）

当 `result_type=need_clarify` 时，后处理输出必须满足以下字段标准：

- `reason_code`（必填）：必须来自 **6A 统一识别原因码**表中的枚举值

- `clarify_slot`（必填）：本次澄清希望用户补充/确认的字段名（见 6A-1.3）

- `candidates`（强烈建议）：候选列表，用于 UI 展示或对话层生成澄清问题

- `prompt_key`（可选）：对话层用于选择话术模板的 key（例如 `CLARIFY_DEVICE`, `CONFIRM_SCOPE_ALL`）

- `target_intent`（可选）：系统希望达成的目标 intent（若已基本确定）

- `confirm_action`（可选）：用于二次确认的结构化摘要（reason_code=risky_action_need_confirm 必须提供）



### 6.1.3 clarify_slot 标准枚举（建议）

为避免对话层字段不一致，`clarify_slot` 建议限定为以下集合（与 SlotDefinitions 对齐）：

- **意图确认**：`intent_L1` / `intent_L2` / `intent_L3`

- **目标对象**：`device_type` / `device_name` / `device_id`

- **位置范围**：`location` / `scope`

- **数值参数**：`brightness` / `volume` / `fan_speed` / `temperature` / `color_temp` / `rgbw_value` / `curtain_position`

- **动作参数**：`power` / `mode` / `music_action` / `track_action` / `channel_action`

- **时间类**：`time` / `duration` / `repeat`

- **服务类**：`request_type` / `service_item`


> 若 `clarify_slot` 不在以上集合中，必须在 `decision_trace` 中记录 `clarify_slot_custom` 并说明原因。


### 6.1.4 candidates 标准结构（建议）

`candidates` 建议使用统一对象结构，便于前端/对话层复用：

- `type`：候选类型（intent/device/location/scene/slot_value）

- `canonical`：标准值（必须能落入 General / Lexicon / Slot enum）

- `display`：展示文本（可选，便于 UI）

- `score`：置信度或排序分（0~1，可选）

- `extra`：扩展字段（如 device_id、room、影响范围摘要等）


### 6.1.5 reason_code 与必填字段约束（强约束）

当命中以下 `reason_code` 时，必须满足对应字段约束：

- `missing_required_slot`：必须提供 `clarify_slot`（缺失字段名）

- `ambiguous_entity`：必须提供 `candidates`（候选实体列表），且 `clarify_slot` 为 `device_name/device_id/location/scene_name` 之一

- `entity_not_found`：必须提供 `clarify_slot`（需要用户指明的对象类型）

- `intent_conflict`：必须提供 `candidates`（候选意图列表）

- `capability_unsupported`：必须提供 `candidates` 或 `supported_intents`（可放在 candidates.extra）

- `risky_action_need_confirm`：必须提供 `confirm_action`（对象/范围/参数摘要）

- `parse_time_failed`：必须提供 `clarify_slot=time` 且给出可解析格式示例（可放 candidates/display）

- `parse_duration_failed`：必须提供 `clarify_slot=duration` 且给出可解析格式示例


### 6.1.6 NeedClarify 优先级（冲突时取最先触发项）

同一次请求可能同时触发多个 need_clarify 原因（例如：既缺 location，又能力不支持）。为保证对话体验一致，后处理需按以下优先级选择 **主 reason_code**：

（1） `risky_action_need_confirm`（风控确认）

（2）`capability_unsupported` / `device_unavailable`（不可执行）

（3） `intent_conflict`（意图未确定）

（4）`ambiguous_entity` / `entity_not_found`（对象未确定）

（5）`missing_required_slot`（参数缺失）

（6）`parse_time_failed` / `parse_duration_failed`（时间解析）

（7）`low_confidence`（兜底）


> 其他同时发生的原因应写入 `decision_trace.additional_reasons[]` 便于回溯。


## 7 意图风控红线（全量枚举）

本节给出**每个 intent_L1** 的默认风控红线策略，用于降低误控与不可逆操作风险。研发实现时需支持：
- 依据 `scope/location/设备歧义/是否服务类请求` 等条件触发 `risky_action_need_confirm`
- 输出 `confirm_action`（结构化确认摘要：对象/范围/参数）供对话层二次确认

| intent_L1 | 风险等级 | 风控红线触发条件（默认） | 后处理要求 |
| --- | --- | --- | --- |
| AC_FANSPEED | 低 | 风速设置全局或缺少目标 | 缺目标 need_clarify |
| AC_MODE | 中 | 切换模式且 scope=all；或与 power/控制模式冲突 | 冲突 need_clarify；全局建议确认（可配置） |
| AC_POWER | 中 | scope=all/whole_house 且 power=off；或未明确房间且存在多空调 | 建议二次确认；否则 need_clarify |
| AC_TEMPERATURE | 中 | 温度设置到边界（<=16 或 >=28）或 scope=all | 边界温度建议二次确认（可配置）；越界 clamp |
| ALARM | 中 | 删除/关闭闹钟或设置长时长 | delete/close 必须二次确认；set 可直接执行（若 time 可解析） |
| CURTAIN_CONTROL | 低 | 对全屋/整层窗帘执行 close/open；或多个窗帘歧义 | 歧义 need_clarify；全局动作可提示确认（可配置） |
| EXIT | 低 | 退出/停止语音 | 可直接执行 |
| FAQ_QUERY | 低 | 查询类 | 可直接执行 |
| HOTEL_CALL | 高 | 拨打酒店/转接人工可能产生打扰/费用 | 必须二次确认 |
| HOUSEKEEPING | 高 | 生成工单/服务请求或打扰服务人员 | 必须二次确认；确认通过后才创建请求 |
| LIGHTING_BRIGHTNESS | 低 | brightness 设置到 0 或 100 且 scope=all/whole_house | 可直接执行；若 scope=all 则建议二次确认（可配置） |
| LIGHTING_COLOR | 低 | RGBW/色温越界或多目标歧义 | 越界 clamp；歧义 need_clarify |
| LIGHTING_POWER | 中 | 当 scope=all/whole_house 或 all_in_location 且 power=off；或未明确目标设备时 | 需要二次确认；无法确认则 need_clarify |
| MUSIC_CONTROL | 低 | 播放/暂停/停止，无明显风险 | 可直接执行 |
| MUSIC_TRACK | 低 | 上一首/下一首，无明显风险 | 可直接执行 |
| MUSIC_VOLUME | 低 | 音量极值或全局 | 同 TV_VOLUME |
| NEED_CLARIFY | 低 | 澄清意图本身 | 系统内部输出 |
| ROOM_SERVICE | 高 | 可能产生费用或生成工单/服务请求 | 必须二次确认；确认通过后才创建请求 |
| SCENE_CONTROL | 高 | 执行/切换场景且 scope=all/whole_house（可能联动多设备） | 必须二次确认；并输出场景影响范围摘要（若可得） |
| SCREEN_POWER | 低 | 屏幕开关，无明显风险 | 可直接执行 |
| SPEAKER_POWER | 中 | 关闭音箱且 scope=all 或存在多音箱歧义 | 歧义 need_clarify；全局建议确认（可配置） |
| SPEAKER_VOLUME | 低 | 音量极值或全局 | 越界 clamp；必要时提示确认（可配置） |
| TIME_QUERY | 低 | 查询类 | 可直接执行 |
| TV_CHANNEL | 低 | 频道号异常（非整数/越界） | 校验失败 need_clarify；越界可 block |
| TV_VOLUME | 低 | 音量设置到极值（0/100）或作用范围为 all | 越界 clamp；必要时提示确认（可配置） |
| WEATHER_QUERY | 低 | 查询类 | 可直接执行 |


> 注：风险等级为产品默认建议，后续可通过配置表引入“risk_level/confirm_policy”字段实现可配置化。


## 7.1 全局跨意图风控红线（全局生效）

以下红线对所有意图全局生效：**触发即 NeedClarify / Fallback，禁止静默猜测执行**。若同时触发多条红线，按 NeedClarify 优先级选择主 reason_code，其余写入 `decision_trace.additional_reasons[]`。


| 红线编号 | 触发条件（任意意图） | 要求（必须执行） | reason_code 建议 |
|---|---|---|---|
| GR-01 | **目标对象不明确**：存在多个候选 device/location/scene，且用户未明确指定 | 必须 need_clarify；返回 candidates 列表 | ambiguous_entity / entity_not_found |
| GR-02 | **范围不明确且影响大**：scope 可能是 all / all_in_location / whole_house（或用户说“全部/全屋/这个房间”但对象不清） | 必须 need_clarify（或二次确认）；禁止默认 scope | risky_action_need_confirm / missing_required_slot |
| GR-03 | **不可逆/高影响操作**：关机/关闭（power=off）、删除/关闭闹钟、执行场景（联动多设备）、服务类请求（可能产生费用/工单） | 必须二次确认（need_clarify）；输出 confirm_action | risky_action_need_confirm |
| GR-04 | **能力不支持**：CapabilityMatrix 中不支持该 intent_L1（或设备域映射失败） | 必须 need_clarify 或 reject；禁止硬执行 | capability_unsupported |
| GR-05 | **枚举非法**：任何枚举值不在 General / Slot enum 内 | 若可回退则 fallback；否则 need_clarify/reject | invalid_enum |
| GR-06 | **时间/时长解析失败**：涉及 time/duration 且无法解析 | 必须 need_clarify；给出可解析格式示例 | parse_time_failed / parse_duration_failed |
| GR-07 | **规则冲突**：同一句话同时命中互斥动作/意图（如 open+close、set+adjust）且无法裁决 | 必须 need_clarify；返回候选意图/动作 | intent_conflict |
| GR-08 | **设备不可用**：目标设备离线/无权限/不在可控清单 | 必须 need_clarify 或 reject；禁止执行 | device_unavailable |
| GR-09 | **置信度不足**：LLM/NLU/词表匹配不足以支撑唯一决策 | 必须 need_clarify；禁止兜底执行 | low_confidence |
| GR-10 | **跨域误触风险**：动作词命中但缺少明确 device_type（例如只说“开一下”） | 必须 need_clarify（询问目标设备/位置） | missing_required_slot / ambiguous_entity |

Fallback 约定：
- 仅允许**向更安全的交互状态**回退（例如：从 execute 回退到 need_clarify/confirm），禁止把不确定性用“默认猜测”吞掉。
- 若产品策略允许“安全降级”（例如从 `scope=all` 降到 `scope=single`），也必须先向用户说明并获取确认（仍然属于 need_clarify）。

## 7.2 intent_L1 分项说明（用途 / 支持设备 / 必填槽位 / 输出示例 / 误控红线）——代码输出示例，需要研发补充

本节按 `intent_L1` 给出统一模板，用于研发实现与测试验收。**必填槽位**为该 L1 下所有规则条目的 required 槽位并集（不删减），具体执行时仍以命中的 `intent_L2/L3` 条目 required 为准。

###7.2.1 AC_FANSPEED

| 字段 | 内容 |
|---|---|
| 用途 | 空调风速/风向控制 |
| 支持设备（来自 IntentDefinitions.device_type） | ac |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | delta、direction、fan_mode、fan_speed、fan_speed_level |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：关键对象/范围/参数不明确时，禁止静默猜测执行；必须 need_clarify。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.2 AC_MODE

| 字段 | 内容 |
|---|---|
| 用途 | 空调模式/控制模式切换 |
| 支持设备（来自 IntentDefinitions.device_type） | ac |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | mode |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 必须澄清：未明确空调对象且存在多个空调；或 mode 与 control_mode/power 冲突时，禁止猜测执行。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.3 AC_POWER

| 字段 | 内容 |
|---|---|
| 用途 | 空调开/关控制 |
| 支持设备（来自 IntentDefinitions.device_type） | ac |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | power |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：当 scope=all 或 all_in_location 且为关闭（power=off）时，必须二次确认；禁止静默执行。
- 必须澄清：若目标设备/位置不明确且存在多个候选设备，禁止默认选一个执行。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.4 AC_TEMPERATURE

| 字段 | 内容 |
|---|---|
| 用途 | 空调温度设置/调节 |
| 支持设备（来自 IntentDefinitions.device_type） | ac |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | delta、direction、temperature、temperature_preset |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 必须澄清：未明确空调对象且存在多个空调；或 mode 与 control_mode/power 冲突时，禁止猜测执行。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.5 ALARM

| 字段 | 内容 |
|---|---|
| 用途 | 闹钟/定时器设定、删除、关闭 |
| 支持设备（来自 IntentDefinitions.device_type） | alarm |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | alarm_action、duration、label、time |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：delete/close 类操作必须二次确认；若缺少 alarm_id 且存在多个闹钟，必须澄清。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.6 CURTAIN_CONTROL

| 字段 | 内容 |
|---|---|
| 用途 | 窗帘开合/停止/位置控制 |
| 支持设备（来自 IntentDefinitions.device_type） | curtain |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | curtain_action、delta_position、position |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 必须澄清：多个窗帘命中或位置/动作冲突（open/close/stop/position 同时出现）时，禁止猜测执行。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.8 EXIT

| 字段 | 内容 |
|---|---|
| 用途 | 退出/停止当前交互 |
| 支持设备（来自 IntentDefinitions.device_type） | system |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | exit_action |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 必须澄清：当 query/location/timezone 等关键参数缺失且无法从上下文补全时，禁止输出伪结果。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.9 FAQ_QUERY

| 字段 | 内容 |
|---|---|
| 用途 | FAQ/知识问答查询 |
| 支持设备（来自 IntentDefinitions.device_type） | faq |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | faq_topic |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 必须澄清：当 query/location/timezone 等关键参数缺失且无法从上下文补全时，禁止输出伪结果。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.10 HOTEL_CALL

| 字段 | 内容 |
|---|---|
| 用途 | 呼叫酒店/人工服务 |
| 支持设备（来自 IntentDefinitions.device_type） | service |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | request_type |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：可能产生费用/工单/联动多设备时，未获得用户明确确认不得执行（必须二次确认）。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.11 HOUSEKEEPING

| 字段 | 内容 |
|---|---|
| 用途 | 客房清洁/物品补给等服务请求 |
| 支持设备（来自 IntentDefinitions.device_type） | service |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | request_type |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：可能产生费用/工单/联动多设备时，未获得用户明确确认不得执行（必须二次确认）。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.12 LIGHTING_BRIGHTNESS

| 字段 | 内容 |
|---|---|
| 用途 | 灯光亮度设置/调节 |
| 支持设备（来自 IntentDefinitions.device_type） | light、rgbw_light |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | brightness、brightness_level、delta、direction |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：关键对象/范围/参数不明确时，禁止静默猜测执行；必须 need_clarify。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.13 LIGHTING_COLOR

| 字段 | 内容 |
|---|---|
| 用途 | 灯光颜色/色温设置 |
| 支持设备（来自 IntentDefinitions.device_type） | rgbw_light |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | color_name、color_temp、delta、direction |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：关键对象/范围/参数不明确时，禁止静默猜测执行；必须 need_clarify。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.14 LIGHTING_POWER

| 字段 | 内容 |
|---|---|
| 用途 | 灯光开/关控制 |
| 支持设备（来自 IntentDefinitions.device_type） | light、rgbw_light |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | power |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：当 scope=all 或 all_in_location 且为关闭（power=off）时，必须二次确认；禁止静默执行。
- 必须澄清：若目标设备/位置不明确且存在多个候选设备，禁止默认选一个执行。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.15 MUSIC_CONTROL

| 字段 | 内容 |
|---|---|
| 用途 | 音乐播放控制（播放/暂停/停止） |
| 支持设备（来自 IntentDefinitions.device_type） | music、speaker |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | play_action |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：关键对象/范围/参数不明确时，禁止静默猜测执行；必须 need_clarify。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.16 MUSIC_TRACK

| 字段 | 内容 |
|---|---|
| 用途 | 音乐切歌（上一首/下一首） |
| 支持设备（来自 IntentDefinitions.device_type） | music、speaker |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | track_action |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：关键对象/范围/参数不明确时，禁止静默猜测执行；必须 need_clarify。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.17 MUSIC_VOLUME

| 字段 | 内容 |
|---|---|
| 用途 | 音乐音量设置/调节 |
| 支持设备（来自 IntentDefinitions.device_type） | music、speaker |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | delta、direction、volume、volume_level |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 必须澄清：当存在多个目标（多个 tv/speaker）且未明确对象时，禁止默认某一台。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.18 NEED_CLARIFY

| 字段 | 内容 |
|---|---|
| 用途 | 澄清意图（系统内部） |
| 支持设备（来自 IntentDefinitions.device_type） | * |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | reason_code |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：关键对象/范围/参数不明确时，禁止静默猜测执行；必须 need_clarify。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.19 ROOM_SERVICE

| 字段 | 内容 |
|---|---|
| 用途 | 送餐/客房服务请求 |
| 支持设备（来自 IntentDefinitions.device_type） | service |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | request_type |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：可能产生费用/工单/联动多设备时，未获得用户明确确认不得执行（必须二次确认）。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.20 SCENE_CONTROL

| 字段 | 内容 |
|---|---|
| 用途 | 场景执行/关闭（可能联动多设备） |
| 支持设备（来自 IntentDefinitions.device_type） | scene |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | scene_action、scene_name |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：可能产生费用/工单/联动多设备时，未获得用户明确确认不得执行（必须二次确认）。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.21 SCREEN_POWER

| 字段 | 内容 |
|---|---|
| 用途 | 屏幕开/关控制 |
| 支持设备（来自 IntentDefinitions.device_type） | screen |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | power |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：关键对象/范围/参数不明确时，禁止静默猜测执行；必须 need_clarify。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.22 SPEAKER_POWER

| 字段 | 内容 |
|---|---|
| 用途 | 音箱开/关控制 |
| 支持设备（来自 IntentDefinitions.device_type） | speaker |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | power |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：当 scope=all 或 all_in_location 且为关闭（power=off）时，必须二次确认；禁止静默执行。
- 必须澄清：若目标设备/位置不明确且存在多个候选设备，禁止默认选一个执行。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.23 SPEAKER_VOLUME

| 字段 | 内容 |
|---|---|
| 用途 | 音箱音量设置/调节 |
| 支持设备（来自 IntentDefinitions.device_type） | speaker |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | delta、direction、volume、volume_level |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 必须澄清：当存在多个目标（多个 tv/speaker）且未明确对象时，禁止默认某一台。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.24 TIME_QUERY

| 字段 | 内容 |
|---|---|
| 用途 | 时间查询 |
| 支持设备（来自 IntentDefinitions.device_type） | time |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | location |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 必须澄清：当 query/location/timezone 等关键参数缺失且无法从上下文补全时，禁止输出伪结果。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.25 TV_CHANNEL

| 字段 | 内容 |
|---|---|
| 用途 | 电视频道切换/选择 |
| 支持设备（来自 IntentDefinitions.device_type） | tv |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | channel、channel_action |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：关键对象/范围/参数不明确时，禁止静默猜测执行；必须 need_clarify。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.26 TV_VOLUME

| 字段 | 内容 |
|---|---|
| 用途 | 电视音量设置/调节 |
| 支持设备（来自 IntentDefinitions.device_type） | tv |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | delta、direction、volume、volume_level |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 必须澄清：当存在多个目标（多个 tv/speaker）且未明确对象时，禁止默认某一台。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。

###7.2.27 WEATHER_QUERY

| 字段 | 内容 |
|---|---|
| 用途 | 天气查询 |
| 支持设备（来自 IntentDefinitions.device_type） | weather |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | location |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 必须澄清：当 query/location/timezone 等关键参数缺失且无法从上下文补全时，禁止输出伪结果。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如“关一下”“调大点”但未指明对象/范围），不得直接执行，必须输出 need_clarify。


## 8 配置表清单与业务含义（SSOT）

本节将你提供的配置表**按原始文件/原始 Sheet**整合到文档中，**不合并、不删减**。以下以 **Markdown 表格**原样呈现（单元格内换行以 `<br>` 保留）。

### 8.1 通用定义表（General.xlsx）—全量内容

#### Sheet: General

| ID | enum_name | values | explanation |
| --- | --- | --- | --- |
| 1 | language | zh-CN, zh-GD, en-US, en-SG | zh-CN：普通话 <br>zh-GD：粤语（广东话） <br>en-US：美式英语 <br>en-SG：新加坡英语 |
| 2 | product_type | lighting_fixtures, temperature_controller, smart_window_treatments, smart_panel, switch, entertainment | lighting_fixtures：照明装置 <br>temperature_controller：温度控制器 smart_window_treatments：智能窗饰 <br>smart_panel：中控屏 <br>switch：开关面板 <br>entertainment：影音娱乐 |
| 3 | device_type | light, rgbw_light, curtain, air_conditioner, television, speaker | light：灯（只控开/关） <br>rgbw_light：RGBW 灯（含双色灯、彩灯等） <br>curtain：窗帘类设备 <br>air_conditioner：空调类设备 <br>television：电视 <br>speaker：音箱 |
| 4 | location | living_room, bedroom, bathroom, balcony, whole_house, bedside, corridor, second_bedroom, kitchen, display_area, conference_room, study_room | living_room：客厅 <br>bedroom：卧室 <br>bathroom：浴室 <br>balcony：阳台 <br>whole_house：全屋 <br>bedside：床头 <br>corridor：走廊 <br>second_bedroom：次卧 <br>kitchen：厨房 <br>display_area：展示区 <br>conference_room：会议室 <br>study_room：书房 |
| 5 | scope | single, all_in_location, all | single：单设备 <br>all_in_location：区域全部 <br>all：全屋全部 |

### 8.2 意图定义表（IntentDefinitions.xlsx）—全量内容

#### Sheet: IntentDefinitions


| ID | intent_L1 | intent_L2 | intent_L3 | device_type | required | optional | description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LGT_PWR_001 | LIGHTING_POWER | SET_POWER | ON_OFF | light,rgbw_light | power | location,scope | light on/off |
| LGT_BRI_001 | LIGHTING_BRIGHTNESS | ADJUST_BRIGHTNESS_RELATIVE | PRECISE_INCREMENT | light,rgbw_light | direction,delta | location,scope | brightness ADJUST +delta |
| LGT_BRI_002 | LIGHTING_BRIGHTNESS | ADJUST_BRIGHTNESS_RELATIVE | VAGUE_INCREMENT | light,rgbw_light | direction | delta,location,scope | brightness ADJUST slightly(默认+20%) |
| LGT_BRI_003 | LIGHTING_BRIGHTNESS | ADJUST_BRIGHTNESS_RELATIVE | PRECISE_DECREMENT | light,rgbw_light | direction,delta | location,scope | brightness ADJUST -delta |
| LGT_BRI_004 | LIGHTING_BRIGHTNESS | ADJUST_BRIGHTNESS_RELATIVE | VAGUE_DECREMENT | light,rgbw_light | direction | delta,location,scope | brightness ADJUST slightly(默认-20%) |
| LGT_BRI_005 | LIGHTING_BRIGHTNESS | SET_BRIGHTNESS_ABSOLUTE | PRECISE | light,rgbw_light | brightness | location,scope | brightness SET to X(0–100) |
| LGT_BRI_006 | LIGHTING_BRIGHTNESS | SET_BRIGHTNESS_ABSOLUTE | VAGUE_High | light,rgbw_light | brightness_level | location,scope | 100 |
| LGT_BRI_007 | LIGHTING_BRIGHTNESS | SET_BRIGHTNESS_ABSOLUTE | VAGUE_Low | light,rgbw_light | brightness_level | location,scope | 5 |
| LGT_BRI_008 | LIGHTING_BRIGHTNESS | SET_BRIGHTNESS_ABSOLUTE | VAGUE_MODERATE | light,rgbw_light | brightness_level | location,scope | 50 |
| LGT_COL_001 | LIGHTING_COLOR | SET_COLOR_TEMPERATURE_ABSOLUTE | PRECISE | rgbw_light | color_temp | location,scope,color_name,rgbw_value | color temp SET to K (precise) |
| LGT_COL_002 | LIGHTING_COLOR | SET_COLOR_TEMPERATURE_ABSOLUTE | VAGUE_COOL  | rgbw_light | color_temp | location,scope,color_name,rgbw_value | 6500 |
| LGT_COL_003 | LIGHTING_COLOR | SET_COLOR_TEMPERATURE_ABSOLUTE | VAGUE_WARM | rgbw_light | color_temp | location,scope,color_name,rgbw_value | 2700 |
| LGT_COL_004 | LIGHTING_COLOR | SET_COLOR_TEMPERATURE_ABSOLUTE | VAGUE_neutral | rgbw_light | color_name | location,scope,color_temp,rgbw_value | 3300 |
| LGT_COL_005 | LIGHTING_COLOR | ADJUST_COLOR_TEMPERATURE_RELATIVE | PRECISE_WARMER | rgbw_light | direction,delta | location,scope,color_temp | color temp ADJUST warmer +deltaK |
| LGT_COL_006 | LIGHTING_COLOR | ADJUST_COLOR_TEMPERATURE_RELATIVE | VAGUE_WARMER | rgbw_light | direction | delta,location,scope,color_temp | color temp ADJUST warmer slightly (default +1000K) |
| LGT_COL_007 | LIGHTING_COLOR | ADJUST_COLOR_TEMPERATURE_RELATIVE | PRECISE_COOLER | rgbw_light | direction,delta | location,scope,color_temp | color temp ADJUST cooler -deltaK |
| LGT_COL_008 | LIGHTING_COLOR | ADJUST_COLOR_TEMPERATURE_RELATIVE | VAGUE_COOLER | rgbw_light | direction | delta,location,scope,color_temp | color temp ADJUST cooler slightly (default -1000K) |
| CUR_001 | CURTAIN_CONTROL | SET_OPEN_RATIO_ABSOLUTE | PRECISE | curtain | curtain_action,position | location,scope,device_name,device_id | Set curtain opening to an explicit ratio (0–100%). Example: “窗帘打开到30%/open curtain to 30%”. |
| CUR_002 | CURTAIN_CONTROL | SET_OPEN_RATIO_ABSOLUTE | VAGUE_MAX | curtain | curtain_action | location,scope,device_name,device_id | Fully open. Postprocess fill: position=100. Example: “窗帘打开/拉到最大”. |
| CUR_003 | CURTAIN_CONTROL | SET_OPEN_RATIO_ABSOLUTE | VAGUE_MIN | curtain | curtain_action | location,scope,device_name,device_id | Fully close. Postprocess fill: position=0. Example: “窗帘关上/拉到最小/close curtains”. |
| CUR_004 | CURTAIN_CONTROL | SET_OPEN_RATIO_ABSOLUTE | VAGUE_MODERATE | curtain | curtain_action | location,scope,device_name,device_id | Open to a moderate level. Postprocess fill: position=50 (configurable). Example: “窗帘开一半/开到中间”. |
| CUR_005 | CURTAIN_CONTROL | ADJUST_OPEN_RATIO_RELATIVE | PRECISE_INCREMENT | curtain | curtain_action,delta_position | location,scope,device_name,device_id | Increase opening by an explicit delta. Example: “再开10%/open 10% more”. |
| CUR_006 | CURTAIN_CONTROL | ADJUST_OPEN_RATIO_RELATIVE | VAGUE_INCREMENT | curtain | curtain_action | delta_position,location,scope,device_name,device_id | Increase opening by a default step. Postprocess fill: delta_position=+20 (configurable). Example: “开大一点/开一点”. |
| CUR_007 | CURTAIN_CONTROL | ADJUST_OPEN_RATIO_RELATIVE | PRECISE_DECREMENT | curtain | curtain_action,delta_position | location,scope,device_name,device_id | Decrease opening by an explicit delta. Example: “关小10%/close 10%”. |
| CUR_008 | CURTAIN_CONTROL | ADJUST_OPEN_RATIO_RELATIVE | VAGUE_DECREMENT | curtain | curtain_action | delta_position,location,scope,device_name,device_id | Decrease opening by a default step. Postprocess fill: delta_position=-20 (configurable). Example: “关一点/小一点”. |
| AC_PWR_001 | AC_POWER | SET_POWER | ON_OFF | ac | power | location,scope | aircon on/off |
| AC_FAN_001 | AC_FANSPEED | SET_FAN_SPEED_LEVEL_ABSOLUTE | PRECISE | ac | fan_speed | fan_direction,location,scope | fan speed set/adjust to X(0–100) |
| AC_FAN_002 | AC_FANSPEED | SET_FAN_SPEED_LEVEL_ABSOLUTE | VAGUE_LEVEL | ac | fan_speed_level | fan_direction,location,scope | fan speed SET to High/Medium/Low (map 100/50/25) |
| AC_FAN_003 | AC_FANSPEED | ADJUST_FAN_SPEED_LEVEL_RELATIVE | PRECISE_INCREMENT | ac | direction,delta | fan_direction,location,scope | fan speed INCREASE by +delta (percentage points) |
| AC_FAN_004 | AC_FANSPEED | ADJUST_FAN_SPEED_LEVEL_RELATIVE | VAGUE_INCREMENT | ac | direction | delta,fan_direction,location,scope | fan speed INCREASE slightly (default +20) |
| AC_FAN_005 | AC_FANSPEED | ADJUST_FAN_SPEED_LEVEL_RELATIVE | PRECISE_DECREMENT | ac | direction,delta | fan_direction,location,scope | fan speed DECREASE by -delta (percentage points) |
| AC_FAN_006 | AC_FANSPEED | ADJUST_FAN_SPEED_LEVEL_RELATIVE | VAGUE_DECREMENT | ac | direction | delta,fan_direction,location,scope | fan speed DECREASE slightly (default -20) |
| AC_FAN_007 | AC_FANSPEED | SET_FAN_MODE | PRECISE | ac | fan_mode | location,scope | fan mode SET (auto/manual) |
| AC_TMP_001 | AC_TEMPERATURE | SET_TEMPERATURE_ABSOLUTE | PRECISE | ac | temperature | location,scope | temperature set/adjust |
| AC_TMP_002 | AC_TEMPERATURE | SET_TEMPERATURE_ABSOLUTE | VAGUE | ac | temperature_preset | location,scope | temperature SET to comfort preset (default 24°C) |
| AC_TMP_003 | AC_TEMPERATURE | ADJUST_TEMPERATURE_RELATIVE | PRECISE_INCREMENT | ac | direction,delta | location,scope | temperature INCREASE by +delta (°C) |
| AC_TMP_004 | AC_TEMPERATURE | ADJUST_TEMPERATURE_RELATIVE | VAGUE_INCREMENT | ac | direction | delta,location,scope | temperature INCREASE slightly (default +1°C) |
| AC_TMP_005 | AC_TEMPERATURE | ADJUST_TEMPERATURE_RELATIVE | PRECISE_DECREMENT | ac | direction,delta | location,scope | temperature DECREASE by -delta (°C) |
| AC_TMP_006 | AC_TEMPERATURE | ADJUST_TEMPERATURE_RELATIVE | VAGUE_DECREMENT | ac | direction | delta,location,scope | temperature DECREASE slightly (default -1°C) |
| AC_MOD_001 | AC_MODE | SET_MODE_ABSOLUTE | DEFAULT | ac | mode | control_mode,power,location,scope | cool/heat/auto/manual etc |
| TV_CH_001 | TV_CHANNEL | SET_CHANNEL_ABSOLUTE | DEFAULT | tv | channel | location,scope |  |
| TV_CH_002 | TV_CHANNEL | ADJUST_CHANNEL_RELATIVE | PREVIOUS | tv | channel_action | location,scope | channel previous |
| TV_CH_003 | TV_CHANNEL | ADJUST_CHANNEL_RELATIVE | NEXT | tv | channel_action | location,scope | channel next |
| TV_VOL_001 | TV_VOLUME | SET_TV_VOLUME_ABSOLUTE | PRECISE | tv | volume | location,scope | volume set/adjust |
| TV_VOL_002 | TV_VOLUME | SET_TV_VOLUME_ABSOLUTE | VAGUE | tv | volume_level | location,scope | volume SET to High/Medium/Low（映射100/50/0） |
| TV_VOL_003 | TV_VOLUME | ADJUST_TV_VOLUME_RELATIVE | PRECISE_INCREMENT | tv | direction,delta | location,scope | volume INCREASE (precise/vague) |
| TV_VOL_004 | TV_VOLUME | ADJUST_TV_VOLUME_RELATIVE | VAGUE_INCREMENT | tv | direction | delta,location,scope | volume INCREASE  (default +20) |
| TV_VOL_005 | TV_VOLUME | ADJUST_TV_VOLUME_RELATIVE | PRECISE_DECREMENT | tv | direction,delta | location,scope | volume DECREASE (precise/vague) |
| TV_VOL_006 | TV_VOLUME | ADJUST_TV_VOLUME_RELATIVE | VAGUE_DECREMENT | tv | direction | delta,location,scope | volume DECREASE  (default -20) |
| SCN_001 | SCENE_CONTROL | SET_SCENE | DEFAULT | scene | scene_action,scene_name | location,scope | turn on/off/switch |
| MUS_CTL_001 | MUSIC_CONTROL | SET_PLAY_ACTION | DEFAULT | music,speaker | play_action | location,scope | play/pause/stop |
| MUS_VOL_001 | MUSIC_VOLUME | SET_VOLUME_ABSOLUTE | PRECISE | music,speaker | volume | location,scope | volume set/adjust |
| MUS_VOL_002 | MUSIC_VOLUME | SET_VOLUME_ABSOLUTE | VAGUE | music,speaker | volume_level | location,scope | music volume SET to High/Medium/Low（映射100/50/0） |
| MUS_VOL_003 | MUSIC_VOLUME | ADJUST_VOLUME_RELATIVE | PRECISE_INCREMENT | music,speaker | direction,delta | location,scope | music volume INCREASE (precise/vague) |
| MUS_VOL_004 | MUSIC_VOLUME | ADJUST_VOLUME_RELATIVE | VAGUE_INCREMENT | music,speaker | direction | delta,location,scope | music volume INCREASE  (default +20) |
| MUS_VOL_005 | MUSIC_VOLUME | ADJUST_VOLUME_RELATIVE | PRECISE_DECREMENT | music,speaker | direction,delta | location,scope | music volume DECREASE (precise/vague) |
| MUS_VOL_006 | MUSIC_VOLUME | ADJUST_VOLUME_RELATIVE | VAGUE_DECREMENT | music,speaker | direction | delta,location,scope | music volume DECREASE  (default -20) |
| MUS_TRK_001 | MUSIC_TRACK | ADJUST_TRACK_RELATIVE | PREVIOUS | music,speaker | track_action | location,scope | prev/next track |
| MUS_TRK_002 | MUSIC_TRACK | ADJUST_TRACK_RELATIVE | NEXT | music,speaker | track_action | location,scope | track previous/next |
| SPK_PWR_001 | SPEAKER_POWER | SET_POWER | ON_OFF | speaker | power | location,scope | speaker on/off |
| SCR_PWR_001 | SCREEN_POWER | SET_POWER | ON_OFF | screen | power | location,scope | screen on/off (bright/off) |
| SPK_VOL_001 | SPEAKER_VOLUME | SET_VOLUME_ABSOLUTE | PRECISE | speaker | volume | location,scope | speaker volume SET to X (0–100) |
| SPK_VOL_002 | SPEAKER_VOLUME | SET_VOLUME_ABSOLUTE | VAGUE | speaker | volume_level | location,scope | speaker volume SET to High/Medium/Low（映射100/50/0） |
| SPK_VOL_003 | SPEAKER_VOLUME | ADJUST_VOLUME_RELATIVE | PRECISE_INCREMENT | speaker | direction,delta | location,scope | speaker volume INCREASE (precise/vague) |
| SPK_VOL_004 | SPEAKER_VOLUME | ADJUST_VOLUME_RELATIVE | VAGUE_INCREMENT | speaker | direction | delta,location,scope | speaker volume INCREASE(default +20) |
| SPK_VOL_005 | SPEAKER_VOLUME | ADJUST_VOLUME_RELATIVE | PRECISE_DECREMENT | speaker | direction,delta | location,scope | speaker volume DECREASE (precise/vague) |
| SPK_VOL_006 | SPEAKER_VOLUME | ADJUST_VOLUME_RELATIVE | VAGUE_DECREMENT | speaker | direction | delta,location,scope | speaker volume DECREASE (default -20) |
| SVC_ROOM_001 | ROOM_SERVICE | CREATE_REQUEST | DEFAULT | service | request_type | details,location,priority | amenity request / ticket |
| SVC_HK_001 | HOUSEKEEPING | CREATE_REQUEST | DEFAULT | service | request_type | details,location,priority | housekeeping request / ticket |
| SVC_CALL_001 | HOTEL_CALL | CREATE_REQUEST | DEFAULT | service | request_type | details,location,priority | call hotel / connect operator |
| Q_WEATHER_001 | WEATHER_QUERY | QUERY | DEFAULT | weather | location | date_range,need_outfit_suggestion | weather / outfit suggestion |
| Q_TIME_001 | TIME_QUERY | QUERY | DEFAULT | time | location | timezone | current time |
| ALARM_001 | ALARM | SETTINGS | DEFAULT | alarm | time,duration | label,repeat | set alarm/timer |
| ALARM_002 | ALARM | DELETE | DEFAULT | alarm | label | alarm_id | delete alarm/timer |
| ALARM_003 | ALARM | CLOSE | DEFAULT | alarm | alarm_action | label | stop alarm/timer |
| FAQ_001 | FAQ_QUERY | QUERY | DEFAULT | faq | faq_topic | language | breakfast/gym etc |
| EXIT_001 | EXIT | EXIT | DEFAULT | system | exit_action | reason | exit/stop voice |
| CLARIFY_001 | NEED_CLARIFY | CLARIFY | DEFAULT | * | reason_code | candidates,prompt_key | safe clarification |


### 8.3 槽位定义表（SlotDefinitions.xlsx）—全量内容

#### Sheet: SlotDefinitions2

| ID | slot | min | max | enum | notes |
| --- | --- | --- | --- | --- | --- |
| SL_001 | alarm_action |  |  | set,delete,close | 闹钟动作：set(设定)/delete(删除)/close(关闭)。 |
| SL_002 | alarm_id |  |  |  | 闹钟唯一标识；用于精确删除/关闭某个闹钟。 |
| SL_003 | brightness | 0.0 | 100.0 |  | 亮度百分比 0–100；越界 clamp 到 [0,100]。 |
| SL_004 | brightness_level |  |  | low,medium,high | 亮度档位；后处理映射：low=25, medium=50, high=100（可配置）。 |
| SL_005 | candidates |  |  |  | 候选意图/候选解析结果列表（建议 JSON 数组），用于澄清展示。 |
| SL_006 | channel | 1.0 | 999.0 |  | 频道号（整数）。 |
| SL_007 | channel_action |  |  | prev,next | 频道切换：prev=上一个；next=下一个。 |
| SL_008 | color_name |  |  | red,green,blue,warm_white,cool_white,white,yellow,purple,pink | 颜色名称；后处理可映射到 rgbw_value 或 color_temp。 |
| SL_009 | color_temp | 2700.0 | 6500.0 |  | 色温（K）2700–6500；支持口语“暖/冷/偏黄/偏白”映射默认值。 |
| SL_010 | control_mode |  |  | auto,manual | 控制模式：auto/manual（若与工作模式分离）。 |
| SL_011 | curtain_action |  |  | open,close,stop | 窗帘动作：open/close/stop（含“拉开/合上/停止”）。 |
| SL_012 | date_range |  |  |  | 日期范围/时间范围（如 today/tomorrow/next 3 days/本周末）。后处理解析为开始/结束日期。 |
| SL_013 | delta | 1.0 | 100.0 |  | 相对调节幅度（正负由 direction 指示）；用于亮度/温度/色温/RGBW 等相对调整。不同设备单位不同（%/°C/K/0–255）。 |
| SL_014 | delta_position | 1.0 | 100.0 |  | 窗帘开合度相对调整幅度（百分点）。与 direction 配合：up=开大；down=关小。 |
| SL_015 | details |  |  |  | 服务请求详情文本（如‘送两条毛巾/空调不制冷’）。可在后处理抽取 item/quantity/故障类型等。 |
| SL_016 | device_id |  |  |  | 设备唯一标识（来自设备列表/注册表）。用于精确指向单设备。 |
| SL_017 | device_name |  |  |  | 设备名称（用户口语/配置名），后处理需做模糊匹配并回填 device_id。 |
| SL_018 | direction |  |  | up,down,left,right | 方向/增减：up=增加/更大；down=减少/更小；left/right 用于支持方向控制的设备（若不支持可忽略）。 |
| SL_019 | duration | 1.0 | 10080.0 |  | 持续时间/延时（分钟）。用于‘10分钟后提醒/响10分钟’等。 |
| SL_020 | exit_action |  |  | exit,stop | 结束会话动作：exit/stop。 |
| SL_021 | fan_direction |  |  | up,down,left,right,auto | 风向：up/down/left/right/auto（按设备支持裁剪）。 |
| SL_022 | fan_mode |  |  | auto,manual,swing | 风模式：auto/manual/swing(摆风)（按设备支持裁剪）。 |
| SL_023 | fan_speed | 0.0 | 100.0 |  | 风速 0–100；也可由档位词映射到 25/50/100。 |
| SL_024 | fan_speed_level |  |  | low,medium,high | 风速档位；后处理映射：low=25, medium=50, high=100（可配置）。 |
| SL_025 | faq_topic |  |  | breakfast,gym,wifi,checkout,pool,parking,spa,restaurant,room_service | FAQ 主题；可按酒店配置扩展。 |
| SL_026 | label |  |  |  | 标签/名称：用于闹钟或请求备注（例：起床/开会提醒）。 |
| SL_027 | language |  |  | zh-CN,zh-GD,en-US,en-SG | 语种/方言标识；用于 ASR/语音播报/界面文案选择。 |
| SL_028 | location |  |  |  | 位置/区域（如 客厅/卧室/全屋 或 城市名）。后处理按上下文映射到房间枚举或地理位置。 |
| SL_029 | mode |  |  | cool,heat,dry,fan,auto | 工作模式：cool/heat/dry/fan/auto；同义词归一（制冷/制热/除湿/送风/自动）。 |
| SL_030 | need_outfit_suggestion |  |  | yes,no | 是否需要穿衣建议；yes/no。 |
| SL_031 | play_action |  |  | play,pause,stop | 播放控制：play/pause/stop。 |
| SL_032 | position | 0.0 | 100.0 |  | 窗帘开合度 0–100；0=全关，100=全开。 |
| SL_033 | power |  |  | on,off | 通用开关；从“打开/关闭/开启/关掉/turn on/off”等归一。 |
| SL_034 | priority |  |  | low,normal,high,urgent | 请求优先级：low/normal/high/urgent。 |
| SL_035 | prompt_key |  |  |  | 澄清提示模板 key（用于前端/对话编排选择提问模板）。 |
| SL_036 | reason |  |  |  | 结束原因/用户反馈（可选）。 |
| SL_037 | reason_code |  |  | missing_slot,ambiguous_device,ambiguous_action,out_of_scope,need_confirm | 需要澄清的原因码。 |
| SL_038 | repeat |  |  |  | 重复规则：once/daily/weekdays/weekends/每周一三五 等；后处理可转换为 RRULE。 |
| SL_039 | request_type |  |  | room_service,housekeeping,hotel_call,workorder,amenity,other | 服务请求类型；与业务路由/工单系统对应。 |
| SL_040 | rgbw_value | 0.0 | 255.0 |  | RGBW 单通道值 0–255；越界 clamp 到 [0,255]。 |
| SL_041 | scene_action |  |  | on,off,switch | 场景动作：on=执行/开启；off=关闭；switch=切换。 |
| SL_042 | scene_name |  |  |  | 场景名称；需与场景库做模糊匹配（如 sleep/relax/movie）。 |
| SL_043 | scope |  |  | single,all_in_location,all | 作用范围：single=单设备；all_in_location=区域全部；all=全屋全部。 |
| SL_044 | temperature | 10.0 | 30.0 |  | 空调温度（°C）10–30；无单位默认按摄氏；越界 clamp。 |
| SL_045 | temperature_preset |  |  | comfort,cool,warm | 温度预设：comfort 默认 24°C；cool 默认 22°C；warm 默认 26°C（均可配置）。 |
| SL_046 | time |  |  |  | 时间点（HH:MM，支持 am/pm、‘早上7点’等口语）。用于闹钟/提醒/定时等。 |
| SL_047 | timezone |  |  |  | IANA 时区（如 Asia/Shanghai, America/Denver）。可由 city/location 推断回填。 |
| SL_048 | track_action |  |  | prev,next | 曲目切换：prev=上一首；next=下一首。 |
| SL_049 | volume | 0.0 | 100.0 |  | 音量 0–100；越界 clamp。 |
| SL_050 | volume_level |  |  | low,medium,high | 音量档位；后处理映射：low=0, medium=50, high=100（可配置）。 |

### 8.4 能力矩阵（CapabilityMatrix.xlsx）—全量内容

#### Sheet: CapabilityMatrix

| ID | device_type | AC_FANSPEED | AC_MODE | AC_POWER | AC_TEMPERATURE | ALARM | CURTAIN_CONTROL | EXIT | FAQ_QUERY | HOTEL_CALL | HOUSEKEEPING | LIGHTING_BRIGHTNESS | LIGHTING_COLOR | LIGHTING_POWER | MUSIC_CONTROL | MUSIC_TRACK | MUSIC_VOLUME | NEED_CLARIFY | ROOM_SERVICE | SCENE_CONTROL | SCREEN_POWER | SPEAKER_POWER | SPEAKER_VOLUME | TIME_QUERY | TV_CHANNEL | TV_VOLUME | WEATHER_QUERY |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CM_001 | light |  |  |  |  |  |  | √ |  |  |  | √ |  | √ |  |  |  | √ |  |  |  |  |  |  |  |  |  |
| CM_002 | rgbw_light |  |  |  |  |  |  | √ |  |  |  | √ | √ | √ |  |  |  | √ |  |  |  |  |  |  |  |  |  |
| CM_003 | curtain |  |  |  |  |  | √ | √ |  |  |  |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  |  |
| CM_004 | ac | √ | √ | √ | √ |  |  | √ |  |  |  |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  |  |
| CM_005 | tv |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  |  | √ |  |  |  |  |  |  | √ | √ |  |
| CM_006 | speaker |  |  |  |  |  |  | √ |  |  |  |  |  |  | √ | √ | √ | √ |  |  |  | √ | √ |  |  |  |  |
| CM_007 | music |  |  |  |  |  |  | √ |  |  |  |  |  |  | √ | √ | √ | √ |  |  |  |  |  |  |  |  |  |
| CM_008 | screen |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  |  | √ |  |  | √ |  |  |  |  |  |  |
| CM_009 | scene |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  |  | √ |  | √ |  |  |  |  |  |  |  |
| CM_010 | service |  |  |  |  |  |  | √ |  | √ | √ |  |  |  |  |  |  | √ | √ |  |  |  |  |  |  |  |  |
| CM_011 | weather |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  | √ |
| CM_012 | time |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  |  | √ |  |  |  |  |  | √ |  |  |  |
| CM_013 | alarm |  |  |  |  | √ |  | √ |  |  |  |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  |  |
| CM_014 | faq |  |  |  |  |  |  | √ | √ |  |  |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  |  |
| CM_015 | system |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  |  | √ |  |  |  |  |  |  |  |  |  |

### 8.5 词表（Lexicon）—全量内容

### Lexicon-device.xlsx

#### Sheet: Lexicon-device2

| ID | lang | category | level | canonical | variants |
| --- | --- | --- | --- | --- | --- |
| LEX_DEV_001 | zh-CN | device | type | light | 灯,灯光,灯具,照明,主灯,大灯,开灯,关灯,灯泡 |
| LEX_DEV_002 | en-US | device | type | light | light,lights,lamp,lamps,lighting,light fixture,ceiling light |
| LEX_DEV_003 | zh-CN | device | type | rgbw_light | 氛围灯,彩灯,变色灯,灯带,情景灯,RGB灯,LED灯带,氛围灯带,彩色灯 |
| LEX_DEV_004 | en-US | device | type | rgbw_light | rgb light,rgbw light,color light,color-changing light,mood light,ambient light,led strip,strip light,light strip |
| LEX_DEV_005 | zh-CN | device | type | curtain | 窗帘,帘子,布帘,纱帘,遮光帘,百叶,百叶窗,卷帘,窗帘布 |
| LEX_DEV_006 | en-US | device | type | curtain | curtain,curtains,drape,drapes,sheer,blackout curtains,window shade,shades,blinds |
| LEX_DEV_007 | zh-CN | device | type | air_conditioner | 空调,冷气,空调机,冷气机,中央空调,制冷,制热 |
| LEX_DEV_008 | en-US | device | type | air_conditioner | air conditioner,ac,a/c,aircon,hvac,air conditioning |
| LEX_DEV_009 | zh-CN | device | type | tv | 电视,电视机,TV,电视屏 |
| LEX_DEV_010 | en-US | device | type | tv | tv,television,tele,smart tv |
| LEX_DEV_011 | zh-CN | device | type | speaker | 音箱,音响,扬声器,喇叭,音响设备 |
| LEX_DEV_012 | en-US | device | type | speaker | speaker,speakers,soundbar,stereo,audio system |
| LEX_DEV_013 | zh-CN | device | type | control_panel | 中控屏,控制屏,控制面板,中控面板,触摸屏,屏幕,智能面板 |
| LEX_DEV_014 | en-US | device | type | control_panel | control panel,smart panel,touch panel,wall panel,panel,screen |
| LEX_DEV_015 | zh-CN | device | type | switch | 开关,开关面板,墙壁开关,电灯开关,面板开关 |
| LEX_DEV_016 | en-US | device | type | switch | switch,wall switch,switch panel,light switch |
| LEX_DEV_017 | zh-CN | device | type | master_switch | 总控,总开关,总制,总掣,电源总控,总电源,总闸 |
| LEX_DEV_018 | en-US | device | type | master_switch | master switch,main switch,all off switch,power master,breaker |
| LEX_DEV_019 | zh-CN | device | type | scene | 勿扰,勿扰模式,清扫,清扫模式 |
| LEX_DEV_020 | en-US | device | type | scene | do not disturb,dnd,cleaning mode,housekeeping mode |
| LEX_DEV_021 | zh-CN | device | type | music | 音乐,歌曲,歌,播放音乐,放歌 |
| LEX_DEV_022 | en-US | device | type | music | music,song,songs,play music,playlist |
| LEX_DEV_023 | zh-CN | device | name | main_light | 主灯,大灯,顶灯,吸顶灯 |
| LEX_DEV_024 | en-US | device | name | main_light | main light,ceiling light,overhead light |
| LEX_DEV_025 | zh-CN | device | name | living_room_light | 客厅灯,客厅主灯,客厅大灯,客厅灯光 |
| LEX_DEV_026 | en-US | device | name | living_room_light | living room light,lounge light,living room lights |
| LEX_DEV_027 | zh-CN | device | name | bedroom_light | 卧室灯,房间灯,卧室主灯,卧室大灯 |
| LEX_DEV_028 | en-US | device | name | bedroom_light | bedroom light,bedroom lights,room light |
| LEX_DEV_029 | zh-CN | device | name | hallway_light | 走廊灯,过道灯,玄关灯 |
| LEX_DEV_030 | en-US | device | name | hallway_light | hallway light,corridor light,entryway light |
| LEX_DEV_031 | zh-CN | device | name | balcony_light | 阳台灯,露台灯 |
| LEX_DEV_032 | en-US | device | name | balcony_light | balcony light,patio light,terrace light |
| LEX_DEV_033 | zh-CN | device | name | bathroom_light | 浴室灯,卫生间灯,洗手间灯,厕所灯 |
| LEX_DEV_034 | en-US | device | name | bathroom_light | bathroom light,restroom light,toilet light |
| LEX_DEV_035 | zh-CN | device | name | recessed_light | 筒灯 |
| LEX_DEV_036 | en-US | device | name | recessed_light | recessed light |
| LEX_DEV_037 | zh-CN | device | name | left_recessed_light | 左边筒灯,左筒灯 |
| LEX_DEV_038 | en-US | device | name | left_recessed_light | left recessed light |
| LEX_DEV_039 | zh-CN | device | name | right_recessed_light | 右边筒灯,右筒灯 |
| LEX_DEV_040 | en-US | device | name | right_recessed_light | right recessed light |
| LEX_DEV_041 | zh-CN | device | name | light_strip | 灯带,LED灯带,氛围灯带,灯条 |
| LEX_DEV_042 | en-US | device | name | light_strip | light strip,led strip,strip light,led tape |
| LEX_DEV_043 | zh-CN | device | name | left_light_strip | 左灯带,左边灯带 |
| LEX_DEV_044 | en-US | device | name | left_light_strip | left light strip,left led strip |
| LEX_DEV_045 | zh-CN | device | name | right_light_strip | 右灯带,右边灯带 |
| LEX_DEV_046 | en-US | device | name | right_light_strip | right light strip,right led strip |
| LEX_DEV_047 | zh-CN | device | name | front_light_strip | 前灯带,前面灯带 |
| LEX_DEV_048 | en-US | device | name | front_light_strip | front light strip,front led strip |
| LEX_DEV_049 | zh-CN | device | name | back_light_strip | 后灯带,后面灯带 |
| LEX_DEV_050 | en-US | device | name | back_light_strip | back light strip,rear light strip,back led strip |
| LEX_DEV_051 | zh-CN | device | name | reading_light | 阅读灯,读书灯 |
| LEX_DEV_052 | en-US | device | name | reading_light | reading light,reading lamp |
| LEX_DEV_053 | zh-CN | device | name | left_reading_light | 左阅读灯,左边阅读灯,左读书灯 |
| LEX_DEV_054 | en-US | device | name | left_reading_light | left reading light,left reading lamp |
| LEX_DEV_055 | zh-CN | device | name | right_reading_light | 右阅读灯,右边阅读灯,右读书灯 |
| LEX_DEV_056 | en-US | device | name | right_reading_light | right reading light,right reading lamp |
| LEX_DEV_057 | zh-CN | device | name | closet_light | 衣柜灯,柜子灯,储物间灯 |
| LEX_DEV_058 | en-US | device | name | closet_light | closet light,wardrobe light,cabinet light |
| LEX_DEV_059 | zh-CN | device | name | vanity_light | 镜前灯,梳妆灯,化妆镜灯 |
| LEX_DEV_060 | en-US | device | name | vanity_light | vanity light,mirror light,makeup light |
| LEX_DEV_061 | zh-CN | device | name | picture_light | 画灯,装饰画灯,壁画灯 |
| LEX_DEV_062 | en-US | device | name | picture_light | picture light,art light,painting light |
| LEX_DEV_063 | zh-CN | device | name | table_lamp | 台灯,桌灯 |
| LEX_DEV_064 | en-US | device | name | table_lamp | table lamp,desk lamp |
| LEX_DEV_065 | zh-CN | device | name | bedside_lamp | 床头灯,床边灯 |
| LEX_DEV_066 | en-US | device | name | bedside_lamp | bedside lamp,bedside light,nightstand lamp |
| LEX_DEV_067 | zh-CN | device | name | accent_light | 氛围灯,装饰灯,点缀灯 |
| LEX_DEV_068 | en-US | device | name | accent_light | accent light,ambient light,mood light |
| LEX_DEV_069 | zh-CN | device | name | ceiling_fan_light | 风扇灯,吊扇灯 |
| LEX_DEV_070 | en-US | device | name | ceiling_fan_light | ceiling fan with light,fan light,ceiling fan light |

### Lexicon-location.xlsx

#### Sheet: Lexicon-location2

| ID | lang | category | level | canonical | variants |
| --- | --- | --- | --- | --- | --- |
| LEX_LOC_001 | zh-CN | location | scope | whole_house | 全屋,全家,整屋,整间屋,成间屋,屋里,屋企,所有房间,全部房间,整个家,全房,（房号）房 |
| LEX_LOC_002 | en-US | location | scope | whole_house | whole house,entire house,whole home,entire home,everywhere,all rooms,the whole place |
| LEX_LOC_003 | zh-CN | location | room | living_room | 客厅,大厅,起居室,会客厅,厅,主厅,公共区域,主区,主要区域 |
| LEX_LOC_004 | en-US | location | room | living_room | living room,lounge,sitting room,main room,common area,living area |
| LEX_LOC_005 | zh-CN | location | room | bedroom | 卧室,房间,睡房,寝室,主人房,主卧,主房,房内,室内,房里 |
| LEX_LOC_006 | en-US | location | room | bedroom | bedroom,room,master bedroom,in the room,inside the room |
| LEX_LOC_007 | zh-CN | location | room | second_bedroom | 次卧,次房,客房,二卧,第二间卧室,副卧 |
| LEX_LOC_008 | en-US | location | room | second_bedroom | second bedroom,guest room,spare bedroom |
| LEX_LOC_009 | zh-CN | location | room | bathroom | 浴室,卫生间,洗手间,厕所,卫浴,冲凉房,沐浴间 |
| LEX_LOC_010 | en-US | location | room | bathroom | bathroom,restroom,toilet,washroom,shower room |
| LEX_LOC_011 | zh-CN | location | room | kitchen | 厨房,厨间,灶间 |
| LEX_LOC_012 | en-US | location | room | kitchen | kitchen |
| LEX_LOC_013 | zh-CN | location | room | balcony | 阳台,露台,平台 |
| LEX_LOC_014 | en-US | location | room | balcony | balcony,patio,terrace |
| LEX_LOC_015 | zh-CN | location | room | corridor | 走廊,过道,通道,玄关,门口走廊 |
| LEX_LOC_016 | en-US | location | room | corridor | hallway,corridor,passage,entryway |
| LEX_LOC_017 | zh-CN | location | position | bedside | 床头,床边,床头边,枕边 |
| LEX_LOC_018 | en-US | location | position | bedside | bedside,by the bed,next to the bed |
| LEX_LOC_019 | zh-CN | location | room | study_room | 书房,学习室,办公区,工作间 |
| LEX_LOC_020 | en-US | location | room | study_room | study,study room,home office,office |
| LEX_LOC_021 | zh-CN | location | room | conference_room | 会议室,会议厅,会场 |
| LEX_LOC_022 | en-US | location | room | conference_room | conference room,meeting room,boardroom |
| LEX_LOC_023 | zh-CN | location | room | display_area | 展示区,展区,陈列区,样板区 |
| LEX_LOC_024 | en-US | location | room | display_area | display area,showroom,exhibit area |

### Lexicon-scene.xlsx

#### Sheet: Lexicon-scene2

| ID | lang | category | level | canonical | variants |
| --- | --- | --- | --- | --- | --- |
| LEX_SCN_001 | zh-CN | scene | scene_name | leave_mode | 离开模式,外出模式,离家模式,出门模式,退房模式,离房,走啦,走了,出去,外出 |
| LEX_SCN_002 | en-US | scene | scene_name | leave_mode | leave mode,away mode,out mode,checkout mode,leaving,i'm leaving,leaving mode |
| LEX_SCN_003 | zh-CN | scene | scene_name | arrive_mode | 入住模式,回房模式,回家模式,回来模式,迎宾模式,抵达模式,到达,进房,回来 |
| LEX_SCN_004 | en-US | scene | scene_name | arrive_mode | arrive mode,arrival mode,welcome mode,home mode,i'm home,back home,check-in mode |
| LEX_SCN_005 | zh-CN | scene | scene_name | reading_mode | 阅读模式,看书模式,读书模式,学习模式,办公模式,复习,温书,睇书 |
| LEX_SCN_006 | en-US | scene | scene_name | reading_mode | reading mode,study mode,work mode,home office mode |
| LEX_SCN_007 | zh-CN | scene | scene_name | soft_mode | 柔和模式,舒适模式,温和模式,柔和一点,柔和点,柔和灯光,柔和 |
| LEX_SCN_008 | en-US | scene | scene_name | soft_mode | soft mode,cozy mode,gentle mode,soft lighting,softer |
| LEX_SCN_009 | zh-CN | scene | scene_name | warm_mode | 温馨模式,温馨一点,温馨一啲,温馨 |
| LEX_SCN_010 | en-US | scene | scene_name | warm_mode | warm mode,cozy mode,warm lighting |
| LEX_SCN_011 | zh-CN | scene | scene_name | sleep_mode | 睡眠模式,睡觉模式,晚安模式,就寝模式,休息模式,瞓觉模式,训觉模式,累了,睡吧 |
| LEX_SCN_012 | en-US | scene | scene_name | sleep_mode | sleep mode,bedtime mode,goodnight mode,rest mode,going to bed |
| LEX_SCN_013 | zh-CN | scene | scene_name | night_mode | 起夜模式,夜起模式,夜灯模式,夜间照明,夜灯,起夜照明 |
| LEX_SCN_014 | en-US | scene | scene_name | night_mode | night mode,night light mode,nighttime mode,midnight mode |
| LEX_SCN_015 | zh-CN | scene | scene_name | winter_mode | 冬日模式,冬天模式,冬季模式 |
| LEX_SCN_016 | en-US | scene | scene_name | winter_mode | winter mode,wintertime mode |
| LEX_SCN_017 | zh-CN | scene | scene_name | summer_mode | 夏日模式,夏天模式,夏季模式 |
| LEX_SCN_018 | en-US | scene | scene_name | summer_mode | summer mode,summertime mode |
| LEX_SCN_019 | zh-CN | scene | scene_name | bright_mode | 明亮模式,光猛模式,灯光明亮,更亮一点,明亮 |
| LEX_SCN_020 | en-US | scene | scene_name | bright_mode | bright mode,full brightness,brighter lighting |
| LEX_SCN_021 | zh-CN | scene | scene_name | wake_mode | 起床模式,早安模式,晨起模式,朝早模式,起身模式,叫我起床,起来模式,早晨,早安 |
| LEX_SCN_022 | en-US | scene | scene_name | wake_mode | wake mode,wake up mode,morning mode,good morning mode,wake me up |
| LEX_SCN_023 | zh-CN | scene | scene_name | ambience_mode | 氛围模式,浪漫模式,娱乐模式,浪漫气氛,氛围,整番个浪漫气氛 |
| LEX_SCN_024 | en-US | scene | scene_name | ambience_mode | ambience mode,mood mode,romance mode,party mode,vibe mode |
| LEX_SCN_025 | zh-CN | scene | scene_name | relax_mode | 轻松模式,放松模式,休闲模式,舒服模式,松一松,叹下,放松一下,轻松 |
| LEX_SCN_026 | en-US | scene | scene_name | relax_mode | relax mode,chill mode,leisure mode,comfort mode,take it easy |
| LEX_SCN_027 | zh-CN | scene | scene_name | movie_mode | 观影模式,电影模式,睇戏模式,电视模式,看电影,看片,睇电视,观影 |
| LEX_SCN_028 | en-US | scene | scene_name | movie_mode | movie mode,cinema mode,tv mode,watching mode,watch a movie |
| LEX_SCN_029 | zh-CN | scene | keyword | scene | 场景,情景,模式,情景模式,场景模式 |
| LEX_SCN_030 | en-US | scene | keyword | scene | scene,mode,preset,setting |

### Lexicon-Action.xlsx

#### Sheet: Lexicon-Action


| ID | lang | canonical_action | intent_hint | variants |
| --- | --- | --- | --- | --- |
| LA_001 | zh-CN | POWER_ON | *Power | 开,打开,开启 |
| LA_002 | zh-CN | POWER_OFF | *Power | 关,关掉,关闭 |
| LA_003 | zh-CN | BRIGHT_UP | LightBrightness | 调亮,亮一点,更亮 |
| LA_004 | zh-CN | BRIGHT_DOWN | LightBrightness | 调暗,暗一点,更暗 |
| LA_005 | zh-CN | COLOR_SET | LightColor | 调成,换成,设为 |
| LA_006 | zh-CN | OPEN | CurtainControl | 打开窗帘,拉开,升起 |
| LA_007 | zh-CN | CLOSE | CurtainControl | 关上窗帘,合上,降下 |
| LA_008 | zh-CN | STOP | CurtainControl | 停,暂停,别动 |
| LA_009 | zh-CN | TEMP_SET | ACTemperature | 调到,设到 |
| LA_010 | zh-CN | COOLER | ACTemperature | 冷一点,更冷 |
| LA_011 | zh-CN | WARMER | ACTemperature | 热一点,更热 |
| LA_012 | zh-CN | FAN_UP | ACFanSpeed | 风大一点,加大 |
| LA_013 | zh-CN | FAN_DOWN | ACFanSpeed | 风小一点,减小 |
| LA_014 | zh-CN | CHANNEL_NEXT | TVChannel | 下一个频道,换台 |
| LA_015 | zh-CN | CHANNEL_PREV | TVChannel | 上一个频道 |
| LA_016 | zh-CN | VOLUME_UP | *Volume | 音量大一点,加大音量 |
| LA_017 | zh-CN | VOLUME_DOWN | *Volume | 音量小一点,减小音量 |
| LA_018 | zh-CN | PLAY | MusicControl | 播放,放歌 |
| LA_019 | zh-CN | PAUSE | MusicControl | 暂停 |
| LA_020 | zh-CN | STOP_PLAY | MusicControl | 关闭音乐,停止 |
| LA_021 | zh-CN | TRACK_NEXT | MusicTrack | 下一首,切歌 |
| LA_022 | zh-CN | TRACK_PREV | MusicTrack | 上一首 |
| LA_023 | zh-CN | SCENE_ON | SceneControl | 开启情景,打开情景 |
| LA_024 | zh-CN | SCENE_OFF | SceneControl | 关闭情景 |
| LA_025 | zh-CN | SCENE_SWITCH | SceneControl | 切换情景 |
| LA_026 | zh-CN | EXIT | ExitVoice | 退出,停止,不用了 |
| LA_027 | en-SG | POWER_ON | *Power | turn on,switch on |
| LA_028 | en-SG | POWER_OFF | *Power | turn off,switch off |
| LA_029 | en-SG | BRIGHT_UP | LightBrightness | brighter,brighten |
| LA_030 | en-SG | BRIGHT_DOWN | LightBrightness | dim,dimme,r dimmer |
| LA_031 | en-SG | OPEN | CurtainControl | open,draw open |
| LA_032 | en-SG | CLOSE | CurtainControl | close,shut,draw closed |
| LA_033 | en-SG | STOP | CurtainControl | stop,hold |
| LA_034 | en-SG | TEMP_SET | ACTemperature | set to,adjust to |
| LA_035 | en-SG | COOLER | ACTemperature | cooler,lower the temperature |
| LA_036 | en-SG | WARMER | ACTemperature | warmer,raise the temperature |
| LA_037 | en-SG | FAN_UP | ACFanSpeed | increase fan,fan stronger |
| LA_038 | en-SG | FAN_DOWN | ACFanSpeed | reduce fan,fan softer |
| LA_039 | en-SG | CHANNEL_NEXT | TVChannel | next channel,channel up |
| LA_040 | en-SG | CHANNEL_PREV | TVChannel | previous channel,channel down |
| LA_041 | en-SG | VOLUME_UP | *Volume | volume up,turn it up |
| LA_042 | en-SG | VOLUME_DOWN | *Volume | volume down,turn it down |
| LA_043 | en-SG | PLAY | MusicControl | play |
| LA_044 | en-SG | PAUSE | MusicControl | pause |
| LA_045 | en-SG | STOP_PLAY | MusicControl | stop music,turn off music |
| LA_046 | en-SG | TRACK_NEXT | MusicTrack | next song,skip |
| LA_047 | en-SG | TRACK_PREV | MusicTrack | previous song |
| LA_048 | en-SG | SCENE_SWITCH | SceneControl | switch scene |
| LA_049 | en-SG | EXIT | ExitVoice | exit,stop listening |


> 注：这些表为 SSOT（Single Source of Truth）。任何实现与校验应以此处内容为准。



## 9. 后处理总体业务流程（必须实现）

### 9.1 流程概览

（1）**locale 确定**：缺省/非法按策略回退（至少支持 language 表）
（2）**动作/实体抽取**：用 Lexicon-Action / device / location / scene 做匹配归一化
（3）**候选意图整理**：结合 LLM 候选、action 的 intent_hint、实体类型、IntentDefinitions 的 required/optional
（4）**能力矩阵 gating**：按设备类型过滤不可支持 intent_L1
（5）**意图裁决**：按 priority、槽位完备度、实体匹配强度选择 final_intent
（6）**槽位归一化与校验**：按 SlotDefinitions 做 enum/range 校验、clamp、默认值策略（如 vague increment 默认 delta）
（7）**输出决策**：满足执行条件 → execute；否则 need_clarify/reject
（8）**trace 记录**：写入命中规则、回退/阻断原因、配置版本

---

## 10. 关键业务规则（研发必须按此落地）

### 10.1 枚举治理（General 表）

* 所有枚举型字段（language/device_type/location/scope/product_type 等）必须命中 General 集合
* 非法处理：

  * 对 `language`：必须回退到合法值（device/session/default）
  * 对执行关键字段（device_type/location/scope 等）：无法纠正则进入 need_clarify 或 reject

### 10.2 能力 gating（Capability Matrix）

* 若 `final_intent.intent_L1` 不被当前 device_type 支持：不得输出 execute
* 必须进入 need_clarify（让用户换说法/换对象）或 reject（视业务策略）


### 10.3 实体解析与歧义处理（Lexicon）

* 命中策略（业务要求）：

（1）先按 locale 匹配 variants
（2） 同时命中多个 canonical → 进入 need_clarify（reason_code=ambiguous_device/ambiguous_location 等）
（3）若无命中但意图需要 device/location → need_clarify

### 10.4 NEED_CLARIFY 意图（闭环要求）

系统必须输出可用于前端/对话层提问的结构化信息：

* `reason_code`：缺槽/歧义/能力不支持
* `clarify_slot`：需要用户补充的字段（如 device_type/location/brightness）
* `candidates`：候选意图/候选设备列表（便于 UI 展示或二次确认）

---

## 10.5 产品侧默认归一化要求（统一策略，避免实现分散）

以下规则在 **SlotDefinitions2.notes / IntentDefinitions.description** 中已出现。为避免实现分散与多处不一致，建议研发将其沉淀为统一策略（可配置、可灰度、可回滚）：

- `brightness_level`：`low=25`, `medium=50`, `high=100`
- `fan_speed_level`：`low=25`, `medium=50`, `high=100`
- `volume_level`：`low=0`, `medium=50`, `high=100`
- `temperature_preset`：`comfort=24°C`, `cool=22°C`, `warm=26°C`（其余预设可在配置中补齐）
- 口语“调亮一点/调暗一点/大一点/小一点”等 **vague 相对调整**：按默认 `delta`（建议 20%，可配置），并遵循 clamp
- 色温口语 **vague warmer/cooler**：默认 `±1000K`（可配置），并遵循 `color_temp` 的范围 clamp（2700–6500）
- 空调温度口语 **vague warmer/cooler**：默认 `±1°C`（可配置），并遵循 `temperature` 的范围 clamp（10–30）
- 窗帘开合口语 **vague increment/decrement**：默认 `delta_position=±20`（可配置），并遵循 `position` 的范围 clamp（0–100）
- 窗帘“开一半/中间”类 **vague moderate**：默认 `position=50`（可配置）

实现约定：
- 若用户已给出精确数值（PRECISE），不得覆盖为默认值；默认策略只用于 VAGUE 场景或槽位缺失但允许补全的场景。
- 所有默认补全必须写入 `decision_trace.slot_validation`（标记 `defaulted`），便于验收与回溯。


## 11. 验收标准（业务验收）

* AC1：输出枚举值闭环（全部在 General/Slot enum 内），否则必须回退/澄清/拒绝且 trace 可定位
* AC2：能力矩阵严格生效（不支持的 intent_L1 不得 execute）
* AC3：槽位范围与 clamp 生效（越界自动 clamp，并在 trace 标识）
* AC4：缺失 required 槽位必进入 need_clarify，并给出 reason_code + clarify_slot + candidates
* AC5：实体/动作命中可追溯（trace 包含命中 variants、来源词表、canonical）

---

## 12. FoodAgent 客房点餐子系统（菜品 + 功能）

> 补充于 2026-06-08。

### 12.1 子系统定位

| 字段 | 内容 |
|---|---|
| 用途 | 客房送餐点餐：菜单查询 / 点单 / 购物车 / 套餐配置 / 下单与取消 |
| 唯一业务工具 | `order_food`（按 `action` 参数分派，见 §12.3） |
| 计价 | 单位 SGD；结算加 **10% 服务费** |
| 供应时段 | 早餐套餐 **06:30–10:30**；其余（汤/配菜/沙拉/汉堡三明治/本地美食/咖啡/茶/果汁）**12:00–21:30** |

### 12.2 菜品全表（9 类 · 26 道）

| 类别 | 菜品 | 价格(SGD) | 关键属性 |
|---|---|---|---|
| **早餐套餐** | 欧式早餐 | 28.00 | 4 必选组：谷物碗 / 牛奶 / 果汁 / 饮品 |
| | 本地早餐 | 28.00 | 3 必选组：粥品 / 果汁 / 饮品 |
| | 活力早餐 | 34.00 | 2 必选组：果汁 / 饮品 |
| **汤** | 每日例汤 | 12.00 | |
| **配菜** | 印度香米 | 7.00 | |
| | 炸薯条 | 10.00 | 素食 |
| | 松露薯条 | 12.00 | 素食 |
| | 迷你春卷 | 12.00 | 素食 |
| **沙拉** | 经典凯撒沙拉 | 20.00 | |
| | 香脆面条沙爹鸡肉沙拉 | 20.00 | 鸡肉 |
| | 柑橘烟熏三文鱼 | 24.00 | 海鲜 |
| **汉堡&三明治** | 总汇三明治 | 24.00 | 猪肉 |
| | 芝士牛肉汉堡 | 26.00 | 牛肉 |
| **本地美食** | 鸡肉沙爹 | 22.00 | 12 串 · 辣 |
| | 羊肉沙爹 | 22.00 | 12 串 · 辣 |
| | 混合沙爹 | 22.00 | 12 串 · 辣 |
| | 海南鸡饭 | 24.00 | |
| | 海鲜河粉 | 26.00 | 海鲜 |
| **咖啡** | 单份意式浓缩 | 6.00 | |
| | 双倍浓缩咖啡 | 9.00 | 可加「冰饮」(+0.50) |
| | 美式咖啡 | 7.00 | 可加「冰饮」(+0.50) |
| **茶** | 伯爵茶 | 6.00 | 壶装 |
| | 纯甘菊花 | 6.00 | 壶装 |
| **果汁** | 苹果汁 | 8.00 | |
| | 葡萄柚汁 | 10.00 | |
| | 橙汁 | 10.00 | |

**套餐必选配置组（required，下单前必须配齐）**
- 欧式早餐：谷物碗（什锦早餐 / 玉米片 / 可可脆片 / 全麸麦片 / Special K）+ 牛奶（鲜牛奶 / 脱脂牛奶 / 豆奶）+ 果汁（橙汁 / 葡萄柚汁 / 西瓜汁）+ 饮品（咖啡 / 茶）
- 本地早餐：粥品（白粥 / 鸡肉粥）+ 果汁 + 饮品
- 活力早餐：果汁 + 饮品

**附加项（addon）**：目前仅「冰饮」（SGD 0.50），**仅美式咖啡 / 双倍浓缩咖啡支持**。

**歧义简称（裸说必须追问款式，不得猜一款）**：薯条 → 炸薯条/松露薯条；沙爹 → 鸡肉/羊肉/混合；沙律 → 3 款沙拉；咖啡/浓缩 → 浓缩款式；茶 → 伯爵/甘菊；早餐 → 欧式/本地/活力。

### 12.3 功能 / 工具（`order_food`，按 action 分派）

| action | 功能 | 关键参数 |
|---|---|---|
| `select_item` | 点独立菜品 | item_name（完整菜名）+ 可选 quantity |
| `select_option` | 套餐配置中选某 group 选项 | group_name + selection_name |
| `modify_option` | 改套餐已选的 group 选项 | item_name + group_name + selection_name |
| `update_quantity` | 改购物车已有菜品数量 | cart_index + quantity |
| `add_addon` | 加附加项（仅「冰饮」） | addon |
| `remove_addon` | 删附加项 | — |
| `add_remark` | 口味 / 过敏备注 | remarks（+ 可选 item_name） |
| `remove_remark` | 删备注 | scope=all/all_for_item + item_name，或 remarks |
| `recommend` | 按过敏 / 饮食限制筛选 | preference_tags |
| `view_order` | 查看购物车 | — |
| `confirm_order` | 确认下单 | — |
| `cancel_order` | 取消 | cancel_scope=last/all，或 item_name / cart_index / quantity |
| `browse_menu` | 打开整本 / 某类菜单（**仅明确「打开/看菜单」**） | 可选 category |


### 12.4 误控红线

| 场景 | 必须 | reason_code 建议 |
|---|---|---|
| 类别裸说（咖啡/沙爹/薯条/沙拉…）未指明款式 | 文字追问列款式 | ambiguous_entity |
| 点 / 问菜单**不存在**的品项 | 文字告知没有 | out_of_scope / entity_not_found |
| 不支持冰饮的品项被要求加冰 | 文字告知不行 | invalid_enum |
| 套餐必选组未配齐就要确认 | 追问缺失选项 | missing_required_slot |

---