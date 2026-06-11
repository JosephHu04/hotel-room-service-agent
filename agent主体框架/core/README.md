# core/ — 核心流水线节点

---

## 这个文件夹是干什么的？

用一句话理解：**这里放的是"处理一个客房请求的标准作业流程（SOP）"。**

每个 .py 文件 = SOP 中的一个步骤。客人请求进来，按 ①→②→③...→⑩ 的顺序依次经过每个节点，每个节点做一件事、做一次判断、写一条记录。

---

## 什么是"节点"？

在你的 Agent 里，一个"节点"就是一个 Python 函数，它的签名统一为：

```python
def xxx_node(state: State) -> dict:
    """从 state 里取数据 → 执行业务逻辑 → 返回要更新的字段"""
    # 1. 读
    user_msg = state["messages"][-1].content
    # 2. 算
    result = do_something(user_msg)
    # 3. 写
    return {"decision_trace": [new_trace_step], "need_clarify": False}
```

然后这些节点在 `room_service_agent.py` 的 `build_graph()` 里像搭积木一样串起来。

---

## 当前进度总览

| # | 节点 | 文件 | 状态 |
|---|------|------|------|
| ① | 内容安全护栏 | `content_safety.py` | ⏳ 在 room_service_agent.py 中，待拆出 |
| ② | **语言检测** | **`locale_resolver.py`** | ✅ **Day 9 完成** |
| ③ | RAG 知识检索 | `rag_retriever.py` | ⏳ 在 room_service_agent.py 中，待拆出 |
| ④ | LLM 意图识别 + 槽位提取 | `chatbot_node.py` | ⏳ 在 room_service_agent.py 中（Day 4 JSON 模式） |
| ⑤ | 槽位校验 | `slot_validator.py` | ✅ Day 5 完成 |
| ⑥ | **实体解析** | **`entity_resolver.py`** | ✅ **Day 9 完成** |
| ⑦ | 能力门控 | `capability_gate.py` | ✅ Day 6 完成 |
| ⑧ | 风控红线 | `risk_checker.py` | ✅ Day 6 完成 |
| ⑨ | 澄清追问构建 | `clarify_builder.py` | ✅ Day 7 完成 |
| ⑩ | 最终输出格式化 | `response_formatter.py` | ✅ Day 7 完成 |

---

## 各节点详细说明

---

### ① 内容安全护栏（guardrail_node）

**位置**：流水线最前面（第一关）
**来源**：通用安全要求

**干什么**：
- 检查用户消息是否包含政治、暴力、色情、赌博、黑客等敏感关键词
- 安全 → 进入 RAG 检索
- 不安全 → 直接拒绝，不再往后走

**与 risk_checker 的区别**：

| 对比维度 | content_safety | risk_checker |
|---------|---------------|--------------|
| 拦截什么 | 恶意/违规内容 | 合法但高风险的操作 |
| 例子 | "怎么黑WiFi" | "打扫所有房间" |
| 结果 | reject（直接拒绝） | need_clarify（要求确认） |

**当前状态**：⚠️ 代码在 `room_service_agent.py` 的 `guardrail_node()` 中，待拆出。

---

### ② 语言检测（locale_resolver） ✅ Day 9 完成

**位置**：guardrail 之后、RAG 之前
**来源**：BRD §10.1 枚举治理 + §9 步骤1

**干什么**：
- 用规则匹配检测用户语言（中文/英文/粤语/新加坡英语）
- 优先级：高置信度信号词 > 中文字符比例 > 英文字符比例 > 默认
- 查 `config/general.json` 的 language 枚举校验合法性
- 检测不到 → 回退默认 `zh-CN`，标记 `locale_missing_defaulted`

**支持的 4 种语言**：zh-CN（普通话）、zh-GD（粤语）、en-US（美式英语）、en-SG（新加坡英语）

**当前状态**：✅ Day 9 完成。

---

### ③ RAG 知识检索（rag_node）

**位置**：locale_resolver 之后
**来源**：LangGraph 标准 RAG 模式

**干什么**：
- 从用户消息提取关键词
- 在 Chroma 向量库中检索 `knowledge/placeholder_info.txt` 的相关内容
- 把检索到的酒店知识拼进 system prompt，帮 LLM 回答更准

**当前状态**：⚠️ 代码在 `room_service_agent.py` 的 `rag_node()` 中，待拆出。

---

### ④ LLM 意图识别 + 槽位提取（chatbot_node） ★ 最核心

**位置**：RAG 检索之后
**来源**：BRD §9 步骤2-3

**干什么**——分三步：

**Step 1 — 拼 prompt**：
- 调用 `prompts/prompt_loader.py` 动态加载完整 system prompt
- prompt 包含：角色定义 + 6条意图表 + 11个槽位表 + 意图判定规则 + 工具铁律 + JSON 格式要求
- 附加 RAG 检索到的酒店知识

**Step 2 — 调 LLM**：
- 使用 JSON 模式的 LLM（`format="json"`，不绑工具）
- 强制 LLM 输出结构化 JSON 而非自然语言

**Step 3 — 解析 JSON**：
- 提取 `intents[]` → 写入 `state.raw_intents`
- 提取 `slots{}` → 写入 `state.raw_slots`
- 提取 `entities{}` → 写入 `state.raw_entities`
- 解析失败 → 标记 `need_clarify=True`，追问客人

**LLM 输出格式**：
```json
{
  "intents": [
    {"L1": "ROOM_SERVICE", "L2": "CREATE_REQUEST", "L3": "DEFAULT",
     "id": "SVC_ROOM_001", "score": 0.95}
  ],
  "slots": {
    "request_type": "amenity",
    "location": "301",
    "details": "两瓶矿泉水"
  },
  "entities": {
    "room": "301",
    "item": "矿泉水"
  }
}
```

**改造前后对比**：

| | 改造前 | 改造后 (Day 4) |
|---|--------|----------------|
| LLM 输出 | 自然语言 "好的我帮你" | 结构化 JSON |
| 意图判断 | LLM 自由决定 | 必须从 intent_definitions 中选 |
| 槽位提取 | 隐式传给工具参数 | 显式提取到 raw_slots |
| 工具调用 | LLM 直接决定调哪个 | 由 tool_executor 根据意图手动路由 |

**当前状态**：⚠️ 代码在 `room_service_agent.py` 的 `chatbot_node()` 中。Day 4 已完成 JSON 模式改造。

---

### ⑤ 槽位校验（slot_validator） ✅ Day 5 完成

**位置**：chatbot 之后、tool_executor 之前
**来源**：BRD §8.3 SlotDefinitions / §9 步骤6 / §10.1 枚举治理 / AC1 AC3 AC4

**干什么**——对 LLM 提取的原始槽位做 4 种校验：

#### 校验 1：enum（枚举校验）

查 `slot_definitions.json` → 如果槽位有 `enum` 字段 → 值必须在列表中。

```
request_type="amenity"  → 在枚举中 → valid ✅
request_type="唱歌"     → 不在枚举 → invalid ❌ → need_clarify
alarm_action="set"      → 在 [set, delete, close] 中 → valid ✅
```

**失败原因码**：`invalid_enum`

#### 校验 2：range（范围校验）

查 `slot_definitions.json` → 如果槽位有 `min`/`max` 字段 → 值在 [min, max] 内。

```
duration=60     → 在 [1, 10080] 内 → valid ✅
duration=50000  → 超出 max → clamp 到 10080 → clamped ⚠️（不阻塞，继续走）
```

**失败原因码**：`out_of_range_clamped`（非阻塞，只是标记 + 自动修正）

#### 校验 3：required（必填检查）

查 `intent_definitions.json` → 找到当前意图 → 检查 `required` 列表中的槽位是否都有值。

```
意图 ALARM_001 → required: [time, duration]
用户说 "明早7点叫醒我" → time="早上7点" ✅, duration 未填
→ 以前：missing_required_slot ❌
→ 现在：duration 有 default=60 → 自动补 → defaulted ✅
```

**失败原因码**：`missing_required_slot`

#### 校验 4：default（默认值补全）

查 `slot_definitions.json` → 意图涉及的 optional 槽位中，有 `default` 字段且用户未填的 → 自动填入。

```
priority   → default="normal"    → 用户没指定 → 自动补 normal
language   → default="zh-CN"     → 用户没指定 → 自动补 zh-CN
duration   → default=60          → 用户没指定 → 自动补 60 分钟
```

**标记**：`defaulted`（非阻塞，告知下游这是自动补的）

#### 槽位的 5 种最终状态

| 状态 | 含义 | 来源 | 是否阻塞 |
|------|------|------|---------|
| `raw` | LLM 原始输出，未校验 | chatbot | — |
| `valid` | 全部校验通过 | slot_validator | ❌ 不阻塞 |
| `clamped` | 越界已自动修正 | slot_validator | ❌ 不阻塞 |
| `defaulted` | 用户未填，系统补了默认值 | slot_validator | ❌ 不阻塞 |
| `invalid` | 校验失败且无法自动修复 | slot_validator | ✅ 阻塞 → need_clarify |

#### 文件结构

```
core/slot_validator.py
├── 第一部分：配置加载（惰性 + 缓存）
├── 第二部分：4 种校验函数
│   ├── validate_enum()        — enum 校验
│   ├── validate_range()       — range 校验 + clamp
│   ├── validate_time_format() — 时间格式校验（口语 + HH:MM）
│   └── validate_location_pattern() — 房间号正则校验
├── 第三部分：主入口 validate_slots()
│   ├── Step 1: 找到主意图
│   ├── Step 2: 逐个校验 LLM 输出的槽位
│   ├── Step 3: 检查 required 槽位
│   ├── Step 4: 补全 default 槽位
│   └── Step 5: 汇总 traces + need_clarify
├── 第四部分：LangGraph 节点函数 slot_validator_node()
└── 第五部分：自测（6 个测试用例）
```

#### 自测结果

| 测试 | 场景 | 预期 | 结果 |
|------|------|------|------|
| Test 1 | 送矿泉水，槽位齐全 | priority 自动补 normal | ✅ |
| Test 2 | 缺 request_type | need_clarify=True | ✅ |
| Test 3 | request_type="唱歌" | invalid_enum | ✅ |
| Test 4 | duration=50000 | clamp 到 10080 | ✅ |
| Test 5 | ALARM 缺 time | missing_required_slot | ✅ |
| Test 6 | location="abc" | 格式不匹配 invalid | ✅ |

---

### ⑥ 实体解析（entity_resolver） ✅ Day 9 完成

**位置**：slot_validator 之后、capability_gate 之前
**来源**：BRD §10.3

**干什么**：
- 优先用 LLM 提取的 entities（room/item）
- 正则 `\d{3,4}` 从全文提取房间号作为补充
- 1 个房间号 → 写入 resolved_entities
- 多个房间号（"301 和 302"）→ `ambiguous_entity` → need_clarify
- 没找到但意图需要 → `entity_not_found` → need_clarify
- ALARM 不需要房间号也能通过

**当前状态**：✅ Day 9 完成。

---

### ⑦ 能力门控（capability_gate） ✅ Day 6 完成

**位置**：slot_validator 之后、risk_checker 之前
**来源**：BRD §10.2 + AC2

**干什么**——查能力矩阵，确保意图能被当前设备类型执行：

1. 从 state.raw_intents 拿主意图
2. 查 `intent_definitions.json` → 获取该意图的 device_type
3. 查 `capability_matrix.json` → 获取该 device_type 的 supported_intents 列表
4. intent.L1 在列表中 → pass
5. 不在 → `capability_unsupported` → need_clarify

**关键注意**：ALARM 的 device_type 是 `alarm`（CM_013），其他三个是 `service`（CM_010）。用错 device_type 会导致 gating 失效。

**能力矩阵速查**：
| device_type | 支持的意图 |
|-------------|-----------|
| service | HOTEL_CALL, HOUSEKEEPING, ROOM_SERVICE, NEED_CLARIFY, EXIT |
| alarm | ALARM |

**文件结构**：
```
capability_gate.py
├── 配置加载（惰性 + 缓存）
├── _resolve_intent() — 从 LLM 输出匹配配置中的意图定义
├── check_capability() — 核心 gating 逻辑
├── capability_gate_node() — LangGraph 节点
└── 自测（7 个测试用例）
```

---

### ⑧ 风控红线（risk_checker） ✅ Day 6 完成

**位置**：capability_gate 之后、tool_executor 之前（最后一道关）
**来源**：BRD §7 + §7.1（GR-01~10）+ §6.1.6

**干什么**——两级检查 + 二次确认流程：

**Level 1 — Intent 级风险**：
- 查 `risk_control.json` 的 intent_risk
- HOUSEKEEPING/HOTEL_CALL/ROOM_SERVICE → 高风险，`require_confirm=true`
- 首次触发 → 发确认消息："为了您的安全，需要确认：XXX。请回复「确认」继续，或「取消」放弃。"
- ALARM 的 delete/close 需确认，set 可直接执行

**Level 2 — 全局红线 GR-01~10**：
- 目前自动检查：GR-03（高风险）、GR-05（枚举非法）、GR-09（低置信度）、GR-10（缺目标）
- 其余红线在 Day 9（entity_resolver）后完善

**二次确认完整流程**：
```
Turn 1:
  客人："打扫302房间"
  → chatbot: JSON解析 → HOUSEKEEPING
  → slot_validator: check pass
  → capability_gate: service 支持 HOUSEKEEPING ✅
  → risk_checker: 高风险 + GR-03 → block
  → 返回: "为了您的安全，需要确认：HOUSEKEEPING 操作。请回复「确认」继续，或「取消」放弃。"
  → state: confirm_pending=True

Turn 2:
  客人："确认"
  → chatbot: 检测到 confirm_pending + 确认关键词
  → 回复: "好的，已确认HOUSEKEEPING操作，马上为您处理。"
  → 放行 → slot_validator → capability_gate → risk_checker 检测到已确认 → pass
  → tool_executor: request_cleaning(302) ✅

Turn 2 (alternate):
  客人："算了"
  → chatbot: 检测到取消关键词
  → 回复: "好的，已取消该操作。"
  → need_clarify=True → END
```

**确认/取消关键词**：
| 确认 | 取消 |
|------|------|
| 确认、好的、行、可以、是的、对、嗯、好、ok、yes、确定 | 算了、不用了、取消、不要、别、no、cancel |

**优先级排序**（BRD §6.1.6）：同时触发多条红线时，按优先级取最高作为主 reason_code，其余写入 additional_reasons。最高优先级：risky_action_need_confirm。

**文件结构**：
```
risk_checker.py
├── 配置加载（惰性 + 缓存）
├── 确认/取消关键词检测
├── _check_intent_risk() — Intent 级风险检查
├── _check_global_rules() — GR-01~10 遍历
├── _prioritize() — 优先级排序
├── check_risks() — 主入口
├── risk_checker_node() — LangGraph 节点（含二次确认流程）
└── 自测（7 个测试用例）
```

---

### ⑨ 澄清追问构建（clarify_builder） ✅ Day 7 完成

**位置**：所有校验失败路径的汇聚点
**来源**：BRD §6.1.1 + §6.1.2 + §6.1.5

**干什么**：
- 所有校验节点失败后，路由到本节点
- 从 decision_trace 自动推断失败原因
- 按 BRD §6.1.5 构建 NeedClarify（每种 reason_code 的必填字段不同）
- 生成自然语言追问消息

**支持的 14 个 reason_code**：
| reason_code | 必填字段 | 话术示例 |
|------------|---------|---------|
| missing_required_slot | clarify_slot | "请问您的房间号是什么呢？" |
| invalid_enum | clarify_slot + candidates | "抱歉，唱歌不在可选范围内。服务类型可选：..." |
| out_of_range_clamped | — | "时长已自动调整为10080分钟" |
| ambiguous_entity | clarify_slot + candidates | "您指的是哪个呢？可选：301, 302" |
| entity_not_found | clarify_slot | "请问具体是哪个呢？" |
| intent_conflict | candidates | "您的需求有几种可能，能具体说说吗？" |
| capability_unsupported | candidates | "当前设备不支持此操作。支持：..." |
| risky_action_need_confirm | confirm_action | "为了您的安全，需要确认：XXX。回复「确认」继续" |
| parse_time_failed | clarify_slot="time" | "抱歉我没能解析成具体时间。请用 HH:MM 格式" |
| parse_duration_failed | clarify_slot="duration" | "请用数字表示时长，如「30分钟」" |
| low_confidence | candidates | "您说的是XXX吗？请确认一下" |

**文件结构**：
```
clarify_builder.py
├── 配置加载（槽位中文名映射）
├── 14 个 reason_code 的话术模板
├── _find_failure_reason() — 从 trace 定位失败原因
├── build_clarify() — 主入口，按优先级构建澄清
├── clarify_builder_node() — LangGraph 节点
└── 自测（6 个测试用例）
```

---

### ⑩ 最终输出格式化（response_formatter） ✅ Day 7 完成

**位置**：流水线最后一个节点（所有路径汇聚于此）
**来源**：BRD §5.2 输出契约 + AC5

**干什么**：
- 收集全链路 decision_trace
- 从 state 推断 result_type（execute/need_clarify/reject）
- 组装 FinalOutput：final_intent + final_slots + resolved_entities + clarify_info + decision_trace
- 生成最终 response_text

**三种输出**：
```json
// execute
{"result_type":"execute", "final_intent":{...}, "final_slots":{...}, "decision_trace":[...], "response_text":"已安排..."}

// need_clarify
{"result_type":"need_clarify", "clarify_info":{"reason_code":"missing_required_slot","clarify_slot":"location"}, "decision_trace":[...], "response_text":"请问您的房间号？"}

// reject
{"result_type":"reject", "decision_trace":[...], "response_text":"抱歉，无法处理..."}
```

**文件结构**：
```
response_formatter.py
├── _result_type() — 推断最终结果类型
├── _build_final_intent() / _build_final_slots() / _build_decision_trace()
├── format_response() — 主入口
├── response_formatter_node() — LangGraph 节点
└── 自测（3 种 result_type）
```

---

## 当前图结构（Day 9）— 12 节点完整流水线

```
START
  │
  ▼ ① guardrail              ← 安全护栏
  │   ├── SAFE →
  │   └── UNSAFE → refuse → ⑨ clarify_builder
  ▼ ③ rag_retrieve            ← RAG 检索
  │
  ▼ ④ chatbot                 ← JSON 模式 LLM（含 confirm_pending）
  │   ├── 成功 →
  │   └── 失败 → ⑨ clarify_builder
  ▼ ⑤ slot_validator          ← 槽位校验
  │   ├── 通过 →
  │   └── 不通过 → ⑨ clarify_builder
  ▼ ⑦ capability_gate         ← 能力门控
  │   ├── 支持 →
  │   └── 不支持 → ⑨ clarify_builder
  ▼ ⑧ risk_checker            ← 风控红线 + 二次确认
  │   ├── 通过 →
  │   └── 拦截/需确认 → ⑨ clarify_builder
  ▼ tool_executor              ← 手动工具路由
  │
  ▼ ⑩ response_formatter      ← ★ 最终输出（Day 7）
  │      ↑
  └── ⑨ clarify_builder ──────┘  ★ 澄清追问（Day 7）
  │
  ▼ END
```

**核心设计**：所有成功路径汇聚到 response_formatter → END，所有失败路径汇聚到 clarify_builder → response_formatter → END。无论走哪条路，客人都会收到标准化的输出。

### 确认流转示例（端到端）

```
Turn 1:
  "打扫302房间"
  → guardrail: SAFE
  → rag_retrieve: context loaded
  → chatbot: JSON {HOUSEKEEPING, request_type=housekeeping, location=302}
  → slot_validator: 3 slots valid (priority=normal defaulted)
  → capability_gate: HOUSEKEEPING supported by service ✅
  → risk_checker: 🔴 high risk → confirm_pending=True
  → "为了您的安全，需要确认：HOUSEKEEPING 操作。请回复「确认」继续，或「取消」放弃。"

Turn 2:
  "确认"
  → guardrail: SAFE
  → chatbot: confirm_pending + 确认 → pass, "好的，已确认，马上处理"
  → slot_validator: pass
  → capability_gate: pass
  → risk_checker: 已确认 → pass
  → tool_executor: request_cleaning(302) → "已安排保洁部打扫302"
```

目标图结构（Day 10）：

```
START
  ▼ ① content_safety  →  UNSAFE → refuse → END
  ▼ ② locale_resolver
  ▼ ③ rag_retrieve
  ▼ ④ chatbot          →  解析失败 → ⑨ clarify_builder → ⑩ response_formatter → END
  ▼ ⑤ slot_validator   →  校验失败 → ⑨ → ⑩ → END
  ▼ ⑥ entity_resolver  →  解析失败 → ⑨ → ⑩ → END
  ▼ ⑦ capability_gate  →  gating 失败 → ⑨ → ⑩ → END
  ▼ ⑧ risk_checker     →  需要确认 → ⑨ → ⑩ → END
  │                       →  客人确认 → 放行
  ▼ 工具调用
  ▼ ⑩ response_formatter
  ▼ END
```
