# config/ — BRD 配置表（JSON 化）

---

## 一句话理解

**这里放的是"酒店服务规则手册"的数字化版本。** BRD 全表是用 Excel 写的，代码没法直接读。我们把 BRD 中和客房服务相关的表格原封不动地转成 JSON 文件放这里。Agent 启动时把这些 JSON 加载到内存，之后所有校验都查这些 JSON，不硬编码任何规则。

---

## 为什么需要这个文件夹？

设想一个场景：三个月后老板说"优先级枚举要加一个 `critical`"。如果规则硬编码在 Python 里：

```
改代码 → 跑测试 → 部署 → 祈祷不出bug
```

但规则在 JSON 里：

```
改一行 JSON → 重启服务 → 生效
```

这就是 BRD 说的 **SSOT（Single Source of Truth，单一事实来源）**——所有业务规则只存在于一个地方，代码只是规则的"执行者"，不是规则的"定义者"。

---

## 五个文件总览

```
客人说："全部打扫一遍"
  │
  ├── ① general.json          → 查 language 枚举、device_type 枚举
  ├── ② intent_definitions.json → 查到 HOUSEKEEPING，required=[request_type]
  │                                device_type=service，risk_level=high
  ├── ③ slot_definitions.json   → 查 request_type 枚举、校验规则
  ├── ④ capability_matrix.json  → service 支持 HOUSEKEEPING → 通过
  └── ⑤ risk_control.json       → HOUSEKEEPING.require_confirm=true
                                   + GR-03（scope=all 不可逆操作）
                                   → 输出: "您确定要打扫全部房间吗？"
```

---

## ① general.json — 通用枚举表

### 一句话

这是酒店系统里"合法词汇的字典"。所有模块校验枚举值时都查它。

### 里面有什么

```
language:    客人能说哪几种语言？
             → 普通话 / 粤语 / 美式英语 / 新加坡英语

device_type: 酒店里有什么类型的设备？
             → 灯 / 彩灯 / 窗帘 / 空调 / 电视 / 音箱 / 服务 / 闹钟

location:    客人可能在什么位置？
             → 客厅 / 卧室 / 浴室 / 阳台 / 全屋 / 床头 / 走廊...

scope:       操作范围有多大？
             → 单个设备 / 区域全部 / 全屋全部
```

### 举个实际例子

客人说"把卧室的灯关了"。LLM 提取 `location=bedroom`，代码去 `general.json` 的 `location.enum` 里一查——有 `bedroom`，合法，通过。

客人说"把狗窝的灯关了"。代码一查——`doghouse` 不在 `location.enum` 列表里 → `invalid_enum` → 要求澄清"您说的是哪个位置？"

### 谁在用

| 节点 | 怎么用 |
|------|--------|
| `locale_resolver.py` | 检查用户说的语言在不在 `language.enum` 里，不在就回退到 `default: zh-CN` |
| `slot_validator.py` | 检查槽位值在不在对应枚举里 |
| `entity_resolver.py` | 检查房间号等实体是否合法 |

### 没有这个文件会怎样

代码里就得写：
```python
if location not in ["living_room", "bedroom", "bathroom", ...]:
```
改一次枚举就要改代码、测代码、部署代码。有了这个文件，改 JSON 就行。

---

## ② intent_definitions.json — 意图定义表

### 一句话

这是你的 Agent 的"营业执照"——规定了你能处理哪些事、每种事需要什么信息、风险有多大。

### 里面有什么：6 条意图

**服务类（device_type = service）**：

| 意图ID | L1 | 场景 | 必填槽位 | 可选槽位 | 风险 |
|--------|-----|------|---------|---------|------|
| SVC_ROOM_001 | ROOM_SERVICE | "送两瓶水到301" | request_type | details, location, priority | high |
| SVC_HK_001 | HOUSEKEEPING | "打扫一下301" | request_type | details, location, priority | high |
| SVC_CALL_001 | HOTEL_CALL | "帮我叫前台" | request_type | details, location, priority | high |

**闹钟类（device_type = alarm）**：

| 意图ID | L1 | L2 | 场景 | 必填槽位 | 可选槽位 | 风险 |
|--------|-----|-----|------|---------|---------|------|
| ALARM_001 | ALARM | SETTINGS | "明早7点叫我" | time, duration | label, repeat | medium |
| ALARM_002 | ALARM | DELETE | "取消闹钟" | label | alarm_id | medium |
| ALARM_003 | ALARM | CLOSE | "关掉闹钟" | alarm_action | label | medium |

### 关键字段解释

| 字段 | 含义 | 谁用 |
|------|------|------|
| `L1 / L2 / L3` | 意图三级分类。L1 是粗分类（ROOM_SERVICE/HOUSEKEEPING/HOTEL_CALL/ALARM），L2/L3 是细分 | chatbot_node 嵌入 prompt；capability_gate 匹配 |
| `device_type` | 这个意图属于哪种设备类型。⚠️ ALARM 的是 `alarm` 不是 `service` | capability_gate 据此查能力矩阵 |
| `required` | 执行前必须有的槽位。缺了 → `missing_required_slot` → 追问 | slot_validator 校验 |
| `optional` | 可以有但非必须的槽位 | slot_validator 参考 |
| `risk_level` | high / medium / low | risk_checker 据此决定要不要二次确认 |
| `require_confirm` | true = 高风险操作，执行前必须先让客人确认 | risk_checker |

### 举个实际例子

LLM 收到"送两瓶水到301"：
1. 根据 intent_definitions.json → 匹配到 `ROOM_SERVICE`（SVC_ROOM_001）
2. 查 `required: ["request_type"]` → 检查槽位里有没有 request_type
3. 查 `require_confirm: true` → 标记高风险，需要二次确认
4. 查 `device_type: service` → 后面 capability_gate 查 service 的能力矩阵

### 谁在用

| 节点 | 怎么用 |
|------|--------|
| `chatbot_node.py` | 把 6 条意图嵌入 system prompt，LLM 才知道"哪些意图是我负责的" |
| `slot_validator.py` | 查 `required` 列表，判断"用户有没有漏掉必填槽位" |
| `risk_checker.py` | 查 `risk_level` 和 `require_confirm`，决定"要不要二次确认" |
| `capability_gate.py` | 查 `device_type`，判断"这个设备能不能执行这个意图" |

---

## ③ slot_definitions.json — 槽位定义表

### 一句话

这是"每个参数的法律规定"——什么值合法、什么范围有效、缺了用什么默认值。

### 里面有什么：11 个槽位

| 槽位 | 类型 | 校验规则 | 默认值 | 用于哪些意图 |
|------|------|---------|--------|------------|
| request_type | enum | 6个枚举值之一 | 无 | 全部3个服务意图 |
| priority | enum | 4个枚举值之一 | normal | 全部3个服务意图 |
| alarm_action | enum | set/delete/close | 无 | ALARM_003 |
| language | enum | 4个枚举值之一 | zh-CN | 全部(*) |
| duration | range | [1.0, 10080.0] 分钟 | 无 | ALARM_001 |
| time | time_format | 需可解析为 HH:MM | 无 | ALARM_001 |
| location | free_text | 正则 `\d{3,4}`（3-4位房间号） | 无 | 全部3个服务意图 |
| details | free_text | 无校验 | 无 | 全部3个服务意图 |
| label | free_text | 无校验 | 无 | ALARM_001/002/003 |
| alarm_id | string | 无校验 | 无 | ALARM_002 |
| repeat | free_text | 无校验 | 无 | ALARM_001 |

### 四种校验类型详解

**enum 校验**（有 `enum` 字段的槽位）：
```
request_type="amenity" → 在枚举列表中 → ✅ valid
request_type="唱歌"   → 不在枚举列表中 → ❌ invalid_enum → 追问
```

**range 校验**（有 `min`/`max` 字段的槽位）：
```
duration=60     → 在 [1, 10080] 内 → ✅ valid
duration=50000  → 超出 max → clamp 到 10080 → ⚠️ out_of_range_clamped
                  → "您设的时长太长了，我帮您改到了7天（10080分钟）"
```

**default 补全**（有 `default` 字段的槽位）：
```
客人说"送两瓶水"没说优先级 → 自动填 priority="normal" → 标记 defaulted
客人明确说"紧急送两瓶水"  → priority="urgent" → 标记 valid
```

**format 校验**（有 `format` 字段的槽位）：
```
time="07:00"     → 能解析为 HH:MM → ✅ valid
time="早上七点"   → 能解析 → ✅ valid
time="过一会儿"   → 无法解析 → ❌ parse_time_failed → 追问
```

### 谁在用

`slot_validator.py` 是**唯一使用者**。校验时逐个查这个文件：
- 有 `enum` → 检查值在不在列表里
- 有 `min`/`max` → 检查值在不在范围内，越界就 clamp
- 有 `default` → 用户没给就自动填入
- 有 `format` → 尝试解析，失败就标记

---

## ④ capability_matrix.json — 能力矩阵

### 一句话

这是"设备能力边界"——规定了每种设备类型能做哪些事。防止"用灯泡来打扫房间"这种荒谬的事。

### 里面有什么

```
service 设备 → 能做：HOTEL_CALL, HOUSEKEEPING, ROOM_SERVICE, NEED_CLARIFY, EXIT
alarm 设备  → 能做：ALARM
```

### 为什么要有这个？

设想这个场景：客人接入了控制 Agent 的一个 **light 设备**（灯泡），却说"帮我打扫房间"。控制 Agent 可能把这个请求转发给你的客房服务 Agent。

你的 `capability_gate.py` 一查：
- 意图是 HOUSEKEEPING → device_type = service
- light 设备 → 查 `capability_matrix["light"]` → light 不在矩阵里（只有 service 和 alarm）
- → `capability_unsupported` → 礼貌拒绝："这个设备不支持打扫请求，请使用客房电话或床头面板。"

### Gating 逻辑（伪代码）

```python
def check_capability(intent, device_type):
    matrix = load("capability_matrix.json")
    supported = matrix[device_type].supported_intents

    if intent.L1 in supported:
        return "pass"                           # ✅ 通过
    else:
        return "capability_unsupported"          # ❌ 拒绝或追问
```

### ⚠️ 最容易出错的地方

ALARM 的 device_type 是 `alarm` 不是 `service`。如果你把 ALARM 意图也当成 service 去查矩阵，就会漏掉 gating 检查——因为 alarm 矩阵里只有 ALARM 一个意图，而 service 矩阵里没有 ALARM。

### 谁在用

`capability_gate.py` 是**唯一使用者**。

---

## ⑤ risk_control.json — 风控红线

### 一句话

这是"什么操作需要客人二次确认"的安全规则。是整个 Agent 的"刹车"。

### 三层结构

#### 第一层：Intent 级风险

你的 6 条意图中有 4 条需要二次确认：

| 意图 | 风险等级 | 需要确认？ | 触发条件 |
|------|---------|-----------|---------|
| HOUSEKEEPING | high | ✅ 是 | 生成工单/打扰服务人员 |
| HOTEL_CALL | high | ✅ 是 | 拨打酒店/转接人工可能产生费用 |
| ROOM_SERVICE | high | ✅ 是 | 可能产生费用 |
| ALARM | medium | ⚠️ 仅 delete/close | set 可直接执行 |

#### 第二层：10 条全局红线（GR-01 ~ GR-10）

不管什么意图，只要命中就触发。挑几条你最可能遇到的：

| 红线 | 触发条件 | 你的处理 |
|------|---------|---------|
| **GR-01** | 目标不明确（如"送一下"没说送什么） | 追问物品名和房间号 |
| **GR-02** | scope=all 未确认（如"全部打扫"） | 二次确认范围 |
| **GR-03** | 不可逆操作（删除闹钟、取消所有服务） | 必须二次确认 |
| **GR-04** | 能力矩阵不支持 | 拒绝或追问 |
| **GR-05** | 枚举值不合法 | 回退或追问 |
| **GR-06** | 时间模糊无法解析（如"过一会儿"） | 追问具体时间 |
| **GR-07** | 意图冲突（同时说"打扫"和"报修"） | 追问主意图 |
| **GR-08** | 设备不可用（如不存在的房间号） | 拒绝或追问 |
| **GR-09** | LLM 置信度不够 | 追问（禁止兜底执行） |
| **GR-10** | 缺必填槽位 | 追问 |

#### 第三层：优先级排序

如果一个请求同时触发多个红线（比如缺槽位 + 高风险 + 时间解析失败），只选一个主 reason_code：

```
risky_action_need_confirm   ← 第1优先（风控确认，最高）
capability_unsupported      ← 第2优先（能力不支持）
device_unavailable          ← 第3优先（设备不可用）
intent_conflict             ← 第4优先（意图冲突）
ambiguous_entity            ← 第5优先（实体歧义）
entity_not_found            ← 第6优先（实体未找到）
missing_required_slot       ← 第7优先（缺少必选槽位）
parse_time_failed           ← 第8优先（时间解析失败）
parse_duration_failed       ← 第9优先（时长解析失败）
low_confidence              ← 第10优先（置信度不足，兜底）
```

其余的 reason_code 写入 `decision_trace.additional_reasons[]`，不丢失信息。

### 二次确认流程

```
客人："全部打扫一遍"
  → risk_checker: GR-02 触发 (scope=all) + GR-03 触发 (不可逆操作)
                 + HOUSEKEEPING 高风险 require_confirm=true
  → 取最高优先级: risky_action_need_confirm
  → 输出: "您确定要打扫全部房间吗？这个操作会生成工单安排保洁人员。"

客人："确认"
  → state.confirm_pending = True
  → 重新进入 risk_checker → 检测到已确认 → 放行，执行

客人："算了不要了"
  → 终止流程
```

### 谁在用

`risk_checker.py` 是**唯一使用者**。

---

## 五个文件的依赖关系图

```
                      ┌─────────────────────┐
                      │  chatbot_node.py    │ ← 嵌入意图定义到 system prompt
                      └────────┬────────────┘
                               │ 读取
                      ┌────────▼────────────┐
                      │ intent_definitions  │
                      │ .json               │
                      └────────┬────────────┘
                               │ 被以下节点读取
          ┌────────────────────┼────────────────────┐
          │                    │                    │
   ┌──────▼──────┐   ┌────────▼────────┐   ┌───────▼───────┐
   │ slot        │   │ capability      │   │ risk          │
   │ validator   │   │ gate            │   │ checker       │
   └──────┬──────┘   └────────┬────────┘   └───────┬───────┘
          │                    │                    │
          │ 读取              │ 读取               │ 读取
   ┌──────▼──────┐   ┌────────▼────────┐   ┌───────▼───────┐
   │ slot        │   │ capability      │   │ risk          │
   │ definitions │   │ matrix          │   │ control       │
   │ .json       │   │ .json           │   │ .json         │
   └──────┬──────┘   └─────────────────┘   └───────────────┘
          │
          │ 也读取
   ┌──────▼──────┐
   │ general     │ ←── locale_resolver 也读取
   │ .json       │ ←── entity_resolver 也读取
   └─────────────┘
```

---

## 核心设计思想

1. **SSOT（单一事实来源）**：所有业务规则只存在于这 5 个 JSON 文件中。代码不硬编码任何规则。

2. **配置即文档**：看 JSON 就能知道"这个 Agent 支持什么、不支持什么、什么场景需要确认"。不需要翻 BRD Excel。

3. **热更新**：改规则只需改 JSON 重启服务，不需要改代码。

4. **可追溯**：每个 JSON 字段都有 `_说明` 或 `brd_source` 指向 BRD 原文，出问题可以回溯到需求。

5. **分层解耦**：
   - `general.json` — 基础词汇表（语言/设备/位置/范围）
   - `intent_definitions.json` — 意图营业执照（能做什么、需要什么）
   - `slot_definitions.json` — 参数法律条文（什么值合法）
   - `capability_matrix.json` — 设备能力边界（谁能做什么）
   - `risk_control.json` — 安全刹车机制（什么要确认）
