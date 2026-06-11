# 语言交互大模型需求说明书（BRD）— 客房服务 Agent 提取版

> **原始文档日期**：2026-01-23  
> **提取日期**：2026-06-09  
> **提取范围**：仅保留与 **客房服务 Agent** 相关的部分（HOUSEKEEPING / HOTEL_CALL / ROOM_SERVICE / ALARM）  
> **原则**：不从原表删改任何内容，只做筛选复制；通用框架章节（§1-§6、§9-§11）各 Agent 共享，一并保留。

---

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
* 不要求一次性把 General 表升级为"逐条 code/alias/fallback/region"的新结构（先兼容现有格式）

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


---

## 7 意图风控红线 — 🏠 客房服务相关意图

> **说明**：以下仅摘取客房服务 Agent 负责的 4 个 intent_L1 的风控红线。  
> 完整表格包含 AC_* / LIGHTING_* / CURTAIN_* / MUSIC_* / TV_* / SCENE_* / SPEAKER_* 等，属于控制 Agent，此处省略。

| intent_L1 | 风险等级 | 风控红线触发条件（默认） | 后处理要求 |
| --- | --- | --- | --- |
| ALARM | 中 | 删除/关闭闹钟或设置长时长 | delete/close 必须二次确认；set 可直接执行（若 time 可解析） |
| HOTEL_CALL | 高 | 拨打酒店/转接人工可能产生打扰/费用 | 必须二次确认 |
| HOUSEKEEPING | 高 | 生成工单/服务请求或打扰服务人员 | 必须二次确认；确认通过后才创建请求 |
| ROOM_SERVICE | 高 | 可能产生费用或生成工单/服务请求 | 必须二次确认；确认通过后才创建请求 |

> 注：风险等级为产品默认建议，后续可通过配置表引入"risk_level/confirm_policy"字段实现可配置化。


## 7.1 全局跨意图风控红线（全局生效）

以下红线对所有意图全局生效：**触发即 NeedClarify / Fallback，禁止静默猜测执行**。若同时触发多条红线，按 NeedClarify 优先级选择主 reason_code，其余写入 `decision_trace.additional_reasons[]`。


| 红线编号 | 触发条件（任意意图） | 要求（必须执行） | reason_code 建议 |
|---|---|---|---|
| GR-01 | **目标对象不明确**：存在多个候选 device/location/scene，且用户未明确指定 | 必须 need_clarify；返回 candidates 列表 | ambiguous_entity / entity_not_found |
| GR-02 | **范围不明确且影响大**：scope 可能是 all / all_in_location / whole_house（或用户说"全部/全屋/这个房间"但对象不清） | 必须 need_clarify（或二次确认）；禁止默认 scope | risky_action_need_confirm / missing_required_slot |
| GR-03 | **不可逆/高影响操作**：关机/关闭（power=off）、删除/关闭闹钟、执行场景（联动多设备）、服务类请求（可能产生费用/工单） | 必须二次确认（need_clarify）；输出 confirm_action | risky_action_need_confirm |
| GR-04 | **能力不支持**：CapabilityMatrix 中不支持该 intent_L1（或设备域映射失败） | 必须 need_clarify 或 reject；禁止硬执行 | capability_unsupported |
| GR-05 | **枚举非法**：任何枚举值不在 General / Slot enum 内 | 若可回退则 fallback；否则 need_clarify/reject | invalid_enum |
| GR-06 | **时间/时长解析失败**：涉及 time/duration 且无法解析 | 必须 need_clarify；给出可解析格式示例 | parse_time_failed / parse_duration_failed |
| GR-07 | **规则冲突**：同一句话同时命中互斥动作/意图（如 open+close、set+adjust）且无法裁决 | 必须 need_clarify；返回候选意图/动作 | intent_conflict |
| GR-08 | **设备不可用**：目标设备离线/无权限/不在可控清单 | 必须 need_clarify 或 reject；禁止执行 | device_unavailable |
| GR-09 | **置信度不足**：LLM/NLU/词表匹配不足以支撑唯一决策 | 必须 need_clarify；禁止兜底执行 | low_confidence |
| GR-10 | **跨域误触风险**：动作词命中但缺少明确 device_type（例如只说"开一下"） | 必须 need_clarify（询问目标设备/位置） | missing_required_slot / ambiguous_entity |

Fallback 约定：
- 仅允许**向更安全的交互状态**回退（例如：从 execute 回退到 need_clarify/confirm），禁止把不确定性用"默认猜测"吞掉。
- 若产品策略允许"安全降级"（例如从 `scope=all` 降到 `scope=single`），也必须先向用户说明并获取确认（仍然属于 need_clarify）。

---

## 7.2 intent_L1 分项说明 — 🏠 客房服务 Agent 专属

> 本节只保留客房服务 Agent 负责的 4 个 intent_L1。其余 intent_L1（AC_* / LIGHTING_* / CURTAIN_* / MUSIC_* / TV_* / SCENE_* / SPEAKER_* / SCREEN_POWER / WEATHER_QUERY / TIME_QUERY / FAQ_QUERY / NEED_CLARIFY / EXIT）分别属于控制 Agent / 咨询 Agent / 公共模块，此处省略。

### 7.2.5 ALARM

| 字段 | 内容 |
|---|---|
| 用途 | 闹钟/定时器设定、删除、关闭 |
| 支持设备（来自 IntentDefinitions.device_type） | alarm |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | alarm_action、duration、label、time |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：delete/close 类操作必须二次确认；若缺少 alarm_id 且存在多个闹钟，必须澄清。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如"关一下""调大点"但未指明对象/范围），不得直接执行，必须输出 need_clarify。

### 7.2.10 HOTEL_CALL

| 字段 | 内容 |
|---|---|
| 用途 | 呼叫酒店/人工服务 |
| 支持设备（来自 IntentDefinitions.device_type） | service |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | request_type |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：可能产生费用/工单/联动多设备时，未获得用户明确确认不得执行（必须二次确认）。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如"关一下""调大点"但未指明对象/范围），不得直接执行，必须输出 need_clarify。

### 7.2.11 HOUSEKEEPING

| 字段 | 内容 |
|---|---|
| 用途 | 客房清洁/物品补给等服务请求 |
| 支持设备（来自 IntentDefinitions.device_type） | service |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | request_type |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：可能产生费用/工单/联动多设备时，未获得用户明确确认不得执行（必须二次确认）。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如"关一下""调大点"但未指明对象/范围），不得直接执行，必须输出 need_clarify。

### 7.2.19 ROOM_SERVICE

| 字段 | 内容 |
|---|---|
| 用途 | 送餐/客房服务请求 |
| 支持设备（来自 IntentDefinitions.device_type） | service |
| 必填槽位（按 L1 汇总，具体以 L2/L3 条目为准） | request_type |


**误控红线 Must-Not（绝对禁止误触 / 必须澄清 / 反例）**
- 绝对禁止误触：可能产生费用/工单/联动多设备时，未获得用户明确确认不得执行（必须二次确认）。

**反例（示例）**
- 用户话术/输入不完整或歧义时（如"关一下""调大点"但未指明对象/范围），不得直接执行，必须输出 need_clarify。

---

## 8 配置表清单 — 🏠 客房服务 Agent 相关部分

### 8.1 通用定义表（General.xlsx）— 客房服务相关列

#### Sheet: General

| ID | enum_name | values | explanation |
| --- | --- | --- | --- |
| 1 | language | zh-CN, zh-GD, en-US, en-SG | zh-CN：普通话 <br>zh-GD：粤语（广东话） <br>en-US：美式英语 <br>en-SG：新加坡英语 |
| 3 | device_type | light, rgbw_light, curtain, air_conditioner, television, speaker | light：灯（只控开/关） <br>rgbw_light：RGBW 灯（含双色灯、彩灯等） <br>curtain：窗帘类设备 <br>air_conditioner：空调类设备 <br>television：电视 <br>speaker：音箱 |
| 4 | location | living_room, bedroom, bathroom, balcony, whole_house, bedside, corridor, second_bedroom, kitchen, display_area, conference_room, study_room | living_room：客厅 <br>bedroom：卧室 <br>bathroom：浴室 <br>balcony：阳台 <br>whole_house：全屋 <br>bedside：床头 <br>corridor：走廊 <br>second_bedroom：次卧 <br>kitchen：厨房 <br>display_area：展示区 <br>conference_room：会议室 <br>study_room：书房 |

> **客房服务 Agent 注**：客房服务 intents（HOUSEKEEPING/HOTEL_CALL/ROOM_SERVICE）的 `device_type` 为 `service`（不在 General 表中，为 BRD 隐含类型）。`location` 枚举用于标识服务请求发生的房间位置。

### 8.2 意图定义表（IntentDefinitions.xlsx）— 客房服务相关行

#### Sheet: IntentDefinitions

> **仅摘取**：SVC_ROOM_001、SVC_HK_001、SVC_CALL_001、ALARM_001、ALARM_002、ALARM_003。  
> 其余行（LGT_*/CUR_*/AC_*/TV_*/MUS_*/SPK_*/SCR_*/SCN_*/Q_*/FAQ_*/EXIT_*/CLARIFY_*）分别属于控制 Agent / 咨询 Agent / 公共模块，此处省略。


| ID | intent_L1 | intent_L2 | intent_L3 | device_type | required | optional | description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SVC_ROOM_001 | ROOM_SERVICE | CREATE_REQUEST | DEFAULT | service | request_type | details,location,priority | amenity request / ticket |
| SVC_HK_001 | HOUSEKEEPING | CREATE_REQUEST | DEFAULT | service | request_type | details,location,priority | housekeeping request / ticket |
| SVC_CALL_001 | HOTEL_CALL | CREATE_REQUEST | DEFAULT | service | request_type | details,location,priority | call hotel / connect operator |
| ALARM_001 | ALARM | SETTINGS | DEFAULT | alarm | time,duration | label,repeat | set alarm/timer |
| ALARM_002 | ALARM | DELETE | DEFAULT | alarm | label | alarm_id | delete alarm/timer |
| ALARM_003 | ALARM | CLOSE | DEFAULT | alarm | alarm_action | label | stop alarm/timer |

> **客房服务 Agent 注**：你的 6 个工具与意图映射关系见文末附录。

### 8.3 槽位定义表（SlotDefinitions.xlsx）— 客房服务相关行

#### Sheet: SlotDefinitions2

> **仅摘取**：客房服务 4 个 intent 的 required + optional 槽位。  
> 其余槽位（brightness/color_temp/power/mode/fan_speed/volume/channel 等）属于控制 Agent，此处省略。


| ID | slot | min | max | enum | notes |
| --- | --- | --- | --- | --- | --- |
| SL_001 | alarm_action |  |  | set,delete,close | 闹钟动作：set(设定)/delete(删除)/close(关闭)。 |
| SL_002 | alarm_id |  |  |  | 闹钟唯一标识；用于精确删除/关闭某个闹钟。 |
| SL_015 | details |  |  |  | 服务请求详情文本（如'送两条毛巾/空调不制冷'）。可在后处理抽取 item/quantity/故障类型等。 |
| SL_019 | duration | 1.0 | 10080.0 |  | 持续时间/延时（分钟）。用于'10分钟后提醒/响10分钟'等。 |
| SL_026 | label |  |  |  | 标签/名称：用于闹钟或请求备注（例：起床/开会提醒）。 |
| SL_027 | language |  |  | zh-CN,zh-GD,en-US,en-SG | 语种/方言标识；用于 ASR/语音播报/界面文案选择。 |
| SL_028 | location |  |  |  | 位置/区域（如 客厅/卧室/全屋 或 城市名）。后处理按上下文映射到房间枚举或地理位置。 |
| SL_034 | priority |  |  | low,normal,high,urgent | 请求优先级：low/normal/high/urgent。 |
| SL_038 | repeat |  |  |  | 重复规则：once/daily/weekdays/weekends/每周一三五 等；后处理可转换为 RRULE。 |
| SL_039 | request_type |  |  | room_service,housekeeping,hotel_call,workorder,amenity,other | 服务请求类型；与业务路由/工单系统对应。 |
| SL_046 | time |  |  |  | 时间点（HH:MM，支持 am/pm、'早上7点'等口语）。用于闹钟/提醒/定时等。 |

> **客房服务 Agent 注**：你的6个工具对应的槽位映射见文末附录。


### 8.4 能力矩阵（CapabilityMatrix.xlsx）— 客房服务相关行

#### Sheet: CapabilityMatrix

> **仅摘取**：`device_type = service` 行（CM_010）。客房服务的 4 个 intent 均路由到 `service`。  
> 其余行分别属于控制 Agent 各设备，此处省略。


| ID | device_type | AC_FANSPEED | AC_MODE | AC_POWER | AC_TEMPERATURE | ALARM | CURTAIN_CONTROL | EXIT | FAQ_QUERY | HOTEL_CALL | HOUSEKEEPING | LIGHTING_BRIGHTNESS | LIGHTING_COLOR | LIGHTING_POWER | MUSIC_CONTROL | MUSIC_TRACK | MUSIC_VOLUME | NEED_CLARIFY | ROOM_SERVICE | SCENE_CONTROL | SCREEN_POWER | SPEAKER_POWER | SPEAKER_VOLUME | TIME_QUERY | TV_CHANNEL | TV_VOLUME | WEATHER_QUERY |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CM_010 | service |  |  |  |  |  |  | √ |  | √ | √ |  |  |  |  |  |  | √ | √ |  |  |  |  |  |  |  |  |

> **关键结论**：`service` 类型支持 `HOTEL_CALL`、`HOUSEKEEPING`、`ROOM_SERVICE`、`NEED_CLARIFY`、`EXIT`。  
> ⚠️ `ALARM` 在 CapabilityMatrix 中归属于 `alarm` 设备类型（CM_013），不在 `service` 下。

---

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

> **客房服务 Agent 相关注**：以下归一化规则中，仅第6项与 ALARM 的 `duration` 相关（如需支持），其余为控制 Agent 的归一化规则。客房服务 Agent 的核心归一化在于 `request_type` 枚举匹配和 `priority` 默认值。

以下规则在 **SlotDefinitions2.notes / IntentDefinitions.description** 中已出现。为避免实现分散与多处不一致，建议研发将其沉淀为统一策略（可配置、可灰度、可回滚）：

- `brightness_level`：`low=25`, `medium=50`, `high=100`
- `fan_speed_level`：`low=25`, `medium=50`, `high=100`
- `volume_level`：`low=0`, `medium=50`, `high=100`
- `temperature_preset`：`comfort=24°C`, `cool=22°C`, `warm=26°C`（其余预设可在配置中补齐）
- 口语"调亮一点/调暗一点/大一点/小一点"等 **vague 相对调整**：按默认 `delta`（建议 20%，可配置），并遵循 clamp
- 色温口语 **vague warmer/cooler**：默认 `±1000K`（可配置），并遵循 `color_temp` 的范围 clamp（2700–6500）
- 空调温度口语 **vague warmer/cooler**：默认 `±1°C`（可配置），并遵循 `temperature` 的范围 clamp（10–30）
- 窗帘开合口语 **vague increment/decrement**：默认 `delta_position=±20`（可配置），并遵循 `position` 的范围 clamp（0–100）
- 窗帘"开一半/中间"类 **vague moderate**：默认 `position=50`（可配置）

实现约定：
- 若用户已给出精确数值（PRECISE），不得覆盖为默认值；默认策略只用于 VAGUE 场景或槽位缺失但允许补全的场景。
- 所有默认补全必须写入 `decision_trace.slot_validation`（标记 `defaulted`），便于验收与回溯。


---

## 11. 验收标准（业务验收）

* AC1：输出枚举值闭环（全部在 General/Slot enum 内），否则必须回退/澄清/拒绝且 trace 可定位
* AC2：能力矩阵严格生效（不支持的 intent_L1 不得 execute）
* AC3：槽位范围与 clamp 生效（越界自动 clamp，并在 trace 标识）
* AC4：缺失 required 槽位必进入 need_clarify，并给出 reason_code + clarify_slot + candidates
* AC5：实体/动作命中可追溯（trace 包含命中 variants、来源词表、canonical）

---

## 附录 A：客房服务 Agent 工具 ↔ BRD 意图映射

| 你的工具函数 | 映射 BRD intent_L1 | 说明 |
|---|---|---|
| `request_cleaning(room_number, time_preference)` | **HOUSEKEEPING** | 打扫房间 |
| `request_supplies(room_number, item, quantity)` | **ROOM_SERVICE** (amenity) | 送毛巾/矿泉水/牙刷等 |
| `order_room_service(room_number, item, quantity)` | **ROOM_SERVICE** | 送餐饮到房间（与点餐 Agent 可能存在边界协商） |
| `report_maintenance(room_number, issue, urgency)` | **HOUSEKEEPING** (workorder) | 报修 → `request_type=workorder` |
| `request_laundry(room_number, items, pickup_time)` | **HOUSEKEEPING** / **ROOM_SERVICE** | 洗衣服务 |
| `set_wake_up_call(room_number, time)` | **ALARM** | 叫醒服务 |

## 附录 B：全局风控红线速查（GR-01~GR-10）

> 客房服务 Agent 必须实现的全局红线检查清单：

| 红线 | 客房服务场景举例 | 处理 |
|---|---|---|
| GR-03 | 用户说"取消所有服务"但未确认 | → `risky_action_need_confirm` |
| GR-03 | 用户说"退房前全部打扫一遍" | → 二次确认 |
| GR-04 | 用户在只有 `light` 的房间请求 `HOUSEKEEPING` | → 应路由到 `service` 域，不影响 |
| GR-06 | 用户说"过一会儿送水" | → `parse_duration_failed` 澄清 |
| GR-09 | 模型不确定是清扫还是补给 | → `low_confidence` 澄清 |
| GR-10 | 用户说"送一下"但没说什么 | → `missing_required_slot` 追问物品名 |

---

*提取完毕。原始 BRD 全表（BRD全表.md）未做任何修改。*
