# models/ — 数据模型定义

---

## 一句话理解

**这里定义了"客房服务 Agent 世界里所有东西长什么样"。**

你的 Agent 在处理一个请求时，数据在不同节点（core/ 下的各个 .py）之间流转。每个节点都需要知道"我收到的数据是什么格式？我要返回的数据是什么格式？" `models.py` 就是这些格式的统一定义。

---

## 为什么需要这个文件夹？

设想如果没有统一的数据模型：
- `slot_validator.py` 返回 `{"error": "缺了request_type"}`
- `risk_checker.py` 期望收到 `{"missing_fields": ["request_type"]}`
- `response_formatter.py` 不知道前面传过来的到底是什么格式，乱猜字段名

有了 `models.py`，所有人 import 同一个 `NeedClarify` 类，字段名、类型全统一。这就是**类型安全**在 Python 里的实现方式——不要各自发明字段名。

---

## 整体结构一览

```
models.py
  │
  ├── 三个枚举（标准词汇表）
  │   ├── ResultType     → 最终结局只有3种: execute / need_clarify / reject
  │   ├── ReasonCode     → 14个标准原因码，出错时统一标记
  │   └── SlotStatus     → 槽位生命周期5种状态: raw → valid/clamped/defaulted/invalid
  │
  ├── 五个核心数据类（数据流转格式）
  │   ├── IntentCandidate   → 一个候选意图（LLM猜的或让客人选的）
  │   ├── Slot              → 单个槽位（LLM提取的某个参数值）
  │   ├── NeedClarify       → 澄清追问结构（告诉客人"你少说了什么"）
  │   ├── DecisionTraceStep → 单条追溯记录（每个节点留一行日志）
  │   └── FinalOutput       → 最终输出（全部信息的汇总，返回给外层）
  │
  └── 三个辅助函数
      ├── make_trace()      → 快捷生成 DecisionTraceStep
      ├── merge_slots()     → 校验后槽位覆盖原始槽位
      └── get_slot_value()  → 安全从槽位字典取值
```

---

## 一、三个枚举

### 1. `ResultType` — 最终结果只有三种

```python
class ResultType(str, Enum):
    EXECUTE = "execute"            # 全部校验通过，可以执行工具
    NEED_CLARIFY = "need_clarify"  # 缺槽/歧义/风险待确认，需要追问客人
    REJECT = "reject"              # 超出能力范围/不安全，礼貌拒绝
```

**为什么继承 `str`**：后面 JSON 序列化时 `result_type.value` 直接是 `"execute"` 字符串，不用额外转换。

**谁用**：全链路最后一个节点 `response_formatter.py` 填这个值，告诉外层（FastAPI / Gradio / 其他 Agent）这个请求的最终结局。

**三种结局的流向**：

```
客人消息进来
  → 10个节点依次处理
  → response_formatter 汇总所有节点结果
  → execute:      校验全过 + 工具执行成功 → 返回执行结果
  → need_clarify: 某节点校验失败 → 返回追问
  → reject:       安全拦截/超范围 → 返回拒绝
```

---

### 2. `ReasonCode` — 14 个标准原因码

```python
class ReasonCode(str, Enum):
    # 槽位相关（5个）
    MISSING_REQUIRED_SLOT = "missing_required_slot"        # 缺必选槽位
    INVALID_ENUM = "invalid_enum"                           # 枚举值不合法
    OUT_OF_RANGE_CLAMPED = "out_of_range_clamped"           # 数值越界已clamp（非阻塞）
    PARSE_TIME_FAILED = "parse_time_failed"                 # 时间解析失败
    PARSE_DURATION_FAILED = "parse_duration_failed"         # 时长解析失败

    # 实体相关（2个）
    AMBIGUOUS_ENTITY = "ambiguous_entity"                   # 实体歧义（多个候选）
    ENTITY_NOT_FOUND = "entity_not_found"                   # 实体未找到

    # 意图相关（2个）
    INTENT_CONFLICT = "intent_conflict"                     # 意图冲突
    LOW_CONFIDENCE = "low_confidence"                       # 置信度不足

    # 能力相关（1个）
    CAPABILITY_UNSUPPORTED = "capability_unsupported"       # 能力矩阵不支持

    # 风控相关（1个）
    RISKY_ACTION_NEED_CONFIRM = "risky_action_need_confirm" # 高风险/不可逆需二次确认

    # 其他（3个）
    DEVICE_UNAVAILABLE = "device_unavailable"               # 设备不可用/离线
    LOCALE_MISSING_DEFAULTED = "locale_missing_defaulted"   # 语言缺失已回退默认
    OUT_OF_SCOPE = "out_of_scope"                           # 超出Agent能力范围
```

**为什么是 14 个**：BRD §6 定义了标准原因码表。每个校验节点失败时，必须从这 14 个里选一个标记——不能自己造词。这样上层（如 `clarify_builder.py`）看到 `ReasonCode.MISSING_REQUIRED_SLOT` 就知道该填 `clarify_slot` 字段。

**每个 ReasonCode 由哪个节点产生**：

| ReasonCode | 产生节点 | 触发场景 |
|-----------|---------|---------|
| missing_required_slot | slot_validator | 缺必填槽位，如只说了"送一下"没说物品 |
| invalid_enum | slot_validator | 枚举值不合法，如 request_type="唱歌" |
| out_of_range_clamped | slot_validator | 数值越界，如 duration=50000 → clamp到10080 |
| parse_time_failed | slot_validator | "过一会儿"无法解析成 HH:MM |
| parse_duration_failed | slot_validator | "响很久"无法解析成数值 |
| ambiguous_entity | entity_resolver | "301和302都需要"两个房间但只有一个location |
| entity_not_found | entity_resolver | 没说房间号但意图需要 |
| intent_conflict | risk_checker | 同时说"打扫"和"报修"，无法判断主意图 |
| low_confidence | chatbot_node | LLM 置信度低于阈值 |
| capability_unsupported | capability_gate | light 设备上试图执行 HOUSEKEEPING |
| risky_action_need_confirm | risk_checker | "全部打扫"未确认 / ALARM delete 未确认 |
| device_unavailable | entity_resolver / capability_gate | 指定了不存在的房间号 |
| locale_missing_defaulted | locale_resolver | 语言检测不到，回退到 zh-CN |
| out_of_scope | content_safety | 敏感内容 / 非酒店服务 |

---

### 3. `SlotStatus` — 一个槽位的五种状态

```python
class SlotStatus(str, Enum):
    RAW = "raw"              # LLM 刚输出的，还没校验
    VALID = "valid"          # 校验通过
    CLAMPED = "clamped"      # 越界被压缩了（如 50000→10080）
    DEFAULTED = "defaulted"  # 用户没填，系统补了默认值
    INVALID = "invalid"      # 校验失败，无法自动修复
```

**生命周期**：

```
LLM 输出             slot_validator 处理后          response_formatter 使用
  raw  ─────────────────→ valid          → "校验通过"
       ─────────────────→ clamped       → "值超标了，已帮您调整"
       ─────────────────→ defaulted     → "没指定，按默认值处理"
       ─────────────────→ invalid       → "值不合法，需要追问"
```

**为什么需要区分 defaulted 和 valid**：response_formatter 需要知道"客人自己说 urgent"和"系统自动填 normal"的区别——后者可能要告知客人"我帮你默认成了普通优先级"。

---

## 二、五个核心数据类

### 1. `IntentCandidate` — 一个候选意图

```python
@dataclass
class IntentCandidate:
    L1: str          # "ROOM_SERVICE" / "HOUSEKEEPING" / "HOTEL_CALL" / "ALARM"
    L2: str          # "CREATE_REQUEST" / "SETTINGS" / "DELETE" / "CLOSE"
    L3: str          # 默认 "DEFAULT"
    id: str          # BRD 意图ID，如 "SVC_ROOM_001"
    score: float     # 置信度 0~1
```

**两种用法**：

| 场景 | 谁产生 | 例子 |
|------|--------|------|
| 正常解析 | chatbot_node | `IntentCandidate("ROOM_SERVICE", "CREATE_REQUEST", "DEFAULT", "SVC_ROOM_001", 0.95)` |
| 意图冲突 | clarify_builder | 返回两个得分相同的候选让客人选 |

---

### 2. `Slot` — 单个槽位（★ 最核心的数据单元）

```python
@dataclass
class Slot:
    name: str               # "request_type", "duration", "location" ...
    value: Any              # "amenity", 60.0, "301" ...
    status: SlotStatus      # raw → valid/clamped/defaulted/invalid
    original_value: Any     # 原始值（clamped时存原始值，如50000）
    message: str            # 人可读说明
```

**四个工厂方法**（不用手动拼 status）：

| 方法 | 使用场景 | 示例 |
|------|---------|------|
| `Slot.from_raw("duration", 60)` | chatbot_node 刚提取完，还没校验 | status=raw, value=60 |
| `Slot.from_default("priority", "normal")` | 客人没指定优先级，系统补 | status=defaulted |
| `Slot.from_clamped("duration", 50000, 10080, "上限")` | 客人说闹钟响50000分钟 | status=clamped, original=50000, value=10080 |
| `Slot.from_invalid("request_type", "唱歌", "不在枚举中")` | 值不合法且无法修复 | status=invalid |

**完整生命周期举例**：

```
客人说："闹钟响50000分钟"
  ↓
chatbot_node:
  Slot.from_raw("duration", 50000)
  → { name: "duration", value: 50000, status: "raw" }
  ↓
slot_validator:
  查 slot_definitions.json → duration.max = 10080
  50000 > 10080 → 越界
  Slot.from_clamped("duration", 50000, 10080, "上限")
  → { name: "duration", value: 10080, status: "clamped",
      original_value: 50000, message: "duration 原始值 50000 超出上限边界，已调整为 10080" }
  ↓
response_formatter:
  看到 status=clamped → 告知客人"您设置的时长太长了，已自动调整为7天"
```

---

### 3. `NeedClarify` — 澄清追问结构

```python
@dataclass
class NeedClarify:
    reason_code: ReasonCode         # 触发了哪个原因码
    clarify_slot: str               # 要追问的字段名，如 "details"
    candidates: list                # 候选列表（让客人选的）
    prompt_key: Optional[str]       # 话术模板key（预留，后期对接i18n）
    target_intent: Optional[IntentCandidate]  # 期望目标意图
    confirm_action: Optional[dict]  # 二次确认摘要（风险场景必填）
```

**不同 reason_code 的字段必填约束**（BRD §6.1.5 强约束）：

| reason_code | clarify_slot | candidates | confirm_action |
|------------|:---:|:---:|:---:|
| missing_required_slot | ✅ 必填 | 可选 | 不需要 |
| ambiguous_entity | ✅ 必填 | ✅ 必填 | 不需要 |
| entity_not_found | ✅ 必填 | 不需要 | 不需要 |
| intent_conflict | 不需要 | ✅ 必填 | 不需要 |
| capability_unsupported | 不需要 | ✅ 必填 | 不需要 |
| risky_action_need_confirm | 不需要 | 不需要 | ✅ 必填 |
| parse_time_failed | ✅ ="time" | ✅ 给示例 | 不需要 |
| parse_duration_failed | ✅ ="duration" | ✅ 给示例 | 不需要 |
| low_confidence | 不需要 | ✅ 必填 | 不需要 |

**举例**：客人说"全部打扫一遍"

```python
NeedClarify(
    reason_code=ReasonCode.RISKY_ACTION_NEED_CONFIRM,
    confirm_action={
        "intent": "HOUSEKEEPING",
        "scope": "all",
        "action": "打扫",
        "summary": "全部房间打扫"
    }
)
# → clarify_builder 据此生成回复："您确定要打扫全部房间吗？这个操作会生成工单安排保洁人员。"
```

---

### 4. `DecisionTraceStep` — 单条追溯记录

```python
@dataclass
class DecisionTraceStep:
    step: str               # 节点名: "slot_validator", "risk_checker" ...
    result: str             # "pass" / "fail" / "clamped" / "defaulted" / "blocked"
    rule_id: Optional[str]  # 命中的规则编号: "GR-03", "SL_019"
    reason_code: Optional[ReasonCode]
    input_data: dict        # 节点输入关键字段
    output_data: dict       # 节点输出关键字段
    message: str            # 人可读说明
```

**每个节点执行后必须输出一条**，最终汇总到 `FinalOutput.decision_trace`。BRD AC5 要求"全链路可追溯"，这就是实现方式。

**一条真实的 trace 记录**：

```python
DecisionTraceStep(
    step="slot_validator",
    result="clamped",
    rule_id="SL_019",
    reason_code=ReasonCode.OUT_OF_RANGE_CLAMPED,
    input_data={"name": "duration", "value": 50000.0},
    output_data={"name": "duration", "value": 10080.0, "original": 50000.0},
    message="duration 50000 超出上限10080，已clamp到10080"
)
```

---

### 5. `FinalOutput` — 最终输出（★ 最重要的数据结构）

```python
@dataclass
class FinalOutput:
    result_type: ResultType                     # 三种结局之一
    decision_trace: list                        # 全链路追溯记录

    # execute 时有值:
    final_intent: Optional[IntentCandidate]     # 确定的意图
    final_slots: dict                           # {槽位名: Slot对象}
    resolved_entities: dict                     # {实体类型: 解析值}

    # need_clarify 时有值:
    clarify_info: Optional[NeedClarify]         # 澄清详情

    # 元信息:
    session_id: str                             # 会话ID（通常用房间号）
    response_text: str                          # 给客人的自然语言回复
```

**三种输出模式**：

```
execute:
{
  "result_type": "execute",
  "final_intent": {"L1":"ROOM_SERVICE", "L2":"CREATE_REQUEST", "L3":"DEFAULT",
                   "id":"SVC_ROOM_001", "score":0.95},
  "final_slots": {
    "request_type": {"name":"request_type", "value":"amenity", "status":"valid"},
    "location":     {"name":"location", "value":"301", "status":"valid"},
    "details":      {"name":"details", "value":"两瓶矿泉水", "status":"valid"},
    "priority":     {"name":"priority", "value":"normal", "status":"defaulted"}
  },
  "resolved_entities": {"room": "301"},
  "decision_trace": [...],
  "response_text": "好的，已为您安排配送两瓶矿泉水到301房间。"
}

need_clarify (缺槽):
{
  "result_type": "need_clarify",
  "clarify_info": {
    "reason_code": "missing_required_slot",
    "clarify_slot": "details",
    "candidates": []
  },
  "decision_trace": [...],
  "response_text": "请问您需要送什么物品呢？"
}

need_clarify (风险确认):
{
  "result_type": "need_clarify",
  "clarify_info": {
    "reason_code": "risky_action_need_confirm",
    "confirm_action": {"intent":"HOUSEKEEPING", "scope":"all",
                       "action":"打扫", "summary":"全部房间打扫"}
  },
  "decision_trace": [...],
  "response_text": "您确定要打扫全部房间吗？这个操作会生成工单安排保洁人员。"
}

reject:
{
  "result_type": "reject",
  "decision_trace": [
    {"step":"content_safety", "result":"blocked", "message":"命中不安全关键词"}
  ],
  "response_text": "抱歉，我是酒店客房服务助手，无法处理该问题。"
}
```

---

## 三、三个辅助函数

### `make_trace()`

快捷构造 DecisionTraceStep。每个节点都用这个函数生成 trace 记录，省去手动写 7 个字段。

```python
trace = make_trace(
    step="slot_validator",
    result="clamped",
    message="duration 50000 超出上限10080，已clamp",
    rule_id="SL_019",
    reason_code=ReasonCode.OUT_OF_RANGE_CLAMPED,
    input_data={"name": "duration", "value": 50000.0},
    output_data={"name": "duration", "value": 10080.0},
)
```

### `merge_slots()`

slot_validator 校验完后，把校验过的槽位覆盖到原始槽位上。

```python
merged = merge_slots(
    raw_slots={"duration": Slot.from_raw("duration", 50000)},
    validated_slots={"duration": Slot.from_clamped("duration", 50000, 10080, "上限"),
                     "priority": Slot.from_default("priority", "normal")},
)
# merged = {"duration": clamped_slot, "priority": defaulted_slot}
```

### `get_slot_value()`

安全地从 slots 字典取值，不存在就返回默认值。

```python
room = get_slot_value(slots, "location", "前台")  # 没location就默认"前台"
```

---

## 数据流全貌

```
客人说："送两瓶水到301"
  │
  ▼
chatbot_node
  ├── IntentCandidate(L1="ROOM_SERVICE", id="SVC_ROOM_001", score=0.95)
  └── Slot("request_type", "amenity", status="raw")
      Slot("location", "301", status="raw")
      Slot("details", "两瓶矿泉水", status="raw")
  │
  ▼
slot_validator
  ├── request_type="amenity" → 查slot_definitions.json → 在enum中 → status="valid"
  ├── location="301" → 正则\d{3,4} → 匹配 → status="valid"
  ├── details → free_text → 无校验 → status="valid"
  └── priority → 用户没说 → 查slot_definitions → default="normal" → Slot.from_default("priority","normal")
  │
  ▼
entity_resolver
  └── location="301" → resolved_entities={"room": "301"}
  │
  ▼
capability_gate
  └── ROOM_SERVICE → device_type=service → 查capability_matrix → 支持 → pass
  │
  ▼
risk_checker
  └── ROOM_SERVICE.require_confirm=true → 首次触发
      → NeedClarify(reason_code="risky_action_need_confirm", confirm_action={...})
      → result_type=need_clarify
  │
  ▼
response_formatter
  └── FinalOutput(
        result_type=need_clarify,
        clarify_info=NeedClarify(...),
        decision_trace=[...]
      )
```

---

## 这一层在整个项目中的位置

```
Day 1-2: config/ JSON   → 定义"什么是合法的"（规则数据）
Day 3:   models/ models.py → 定义"数据长什么样"（数据契约）★ 你在看这个
Day 4:   prompts/       → 定义"LLM 怎么理解任务"（提示词）
Day 5-7: core/           → 定义"数据怎么校验"（业务逻辑）
Day 8-10: tools/ + tests/ → 定义"数据怎么执行和验证"（执行层）
```

models.py 是整个流水线的**契约层**——后面所有节点都按这个契约读写数据。它不上不下的位置决定了：向下对接 config 的原始数据，向上给 core 节点提供标准化的数据结构。
