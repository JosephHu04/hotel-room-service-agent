# 什么是真正的 Agent？—— 方向反思笔记

> 写于 2026-06-11，与 Claude 讨论后整理。
> 起因：老师看完我的项目后指出"方向是错的，不应该用规则去限制死大模型"。

---

## 一、我做的是什么？（流水线架构）

我的架构本质上是一个 **12 节点的 LangGraph 流水线**：

```
用户输入 → 护栏 → 语言检测 → RAG → LLM提取JSON → 槽位校验 → 实体解析 → 能力门控 → 风控检查 → 工具执行 → 澄清构建 → 格式化输出
```

LLM（大模型）只是其中一个节点——用来把用户的话转成结构化 JSON。后面的槽位校验、实体解析、能力门控、风控检查……全是硬编码的 Python 规则。

### 这其实是什么？

**这就是传统 NLP 对话系统的架构**：意图识别 → 槽位填充 → 校验 → 执行。

我只是把原来的机器学习分类器换成了 LLM，但架构思想没变。这是 1990s-2010s 的**帧基对话系统（Frame-based Dialogue System）**思路。

---

## 二、老师为什么说方向错了？

核心问题：**用代码去替代 LLM 做决策。**

我的代码里有大量这种逻辑：

```python
# 我替 LLM 判断该用什么工具
HOUSEKEEPING_TOOL_MAP = {
    "housekeeping": "request_cleaning",
    "workorder":    "report_maintenance",
    "amenity":      "request_laundry",
}

# 我替 LLM 判断缺什么信息
if L1 in ("ROOM_SERVICE", "HOUSEKEEPING", "HOTEL_CALL"):
    missing = []
    if not room:
        missing.append("房间号")
    if not detail and L1 != "HOTEL_CALL":
        missing.append("具体需求")
```

这些规则本质上是在说：**"LLM 我不信任你，我来帮你判断。"**

### 但问题是——LLM 其实能做得更好。

- 规则"没匹配到房间号格式 → 追问"，但 LLM 完全能理解"我那屋有点冷"也是在说房间
- 规则"request_type=amenity → request_laundry"，但客人说"帮我熨一下西装"时 LLM 自己就知道该调洗衣服务
- 每增加一条规则，就多一个盲点。LLM 的泛化能力正是用来覆盖这些盲点的

---

## 三、什么才是真正的 Agent？

### 一句话定义

> **Agent = LLM（大脑） + 工具（手） + 自主决策循环**

### 关键区别：谁在做决策？

| 维度 | 我的架构（流水线） | 真正的 Agent 架构 |
|------|-------------------|-------------------|
| **谁决定下一步做什么？** | 代码（硬编码的图） | LLM 自己 |
| **LLM 的角色** | NLU 组件（输出 JSON） | 中央决策者 |
| **工具调用** | 代码根据 intent 查表决定 | LLM 自己决定调哪个工具、什么时候调 |
| **信息不足时** | 代码检测字段缺失 → 追问 | LLM 自己意识到信息不够 → 主动追问 |
| **异常处理** | 每个节点有自己的兜底逻辑 | LLM 观察工具返回结果，自己判断要不要重试/追问 |

用更直白的话说：**我现在是让代码指挥 LLM，而 Agent 应该是让 LLM 指挥代码。**

---

## 四、举个例子对比

用户说："帮我送两瓶水到 301"

### 我的流水线（12 步）：

1. `guardrail_node` — 关键词检查是否包含政治/色情
2. `locale_resolver_node` — 检测语言
3. `rag_node` — 检索知识库
4. `chatbot_node` — 调 LLM，强制输出 JSON `{"intents":[{"L1":"ROOM_SERVICE"}], "slots":{...}}`
5. `slot_validator` — Python 代码检查：location 有值 ✓，details 有值 ✓
6. `entity_resolver` — Python 代码查表：301 是有效房间号 ✓
7. `capability_gate` — Python 代码查 capability_matrix.json ✓
8. `risk_checker` — Python 代码查 risk_control.json → 高风险 → 二次确认
9. `tool_executor` — Python 代码查 INTENT_TOOL_MAP → `request_supplies`
10. `clarify_builder` — 构建澄清结构（本例不走）
11. `response_formatter` — 格式化输出
12. 返回结果

### 真正的 Agent（2-3 步）：

```
Step 1: LLM 收到消息 "帮我送两瓶水到301"
        → LLM 自己想：客房物品补给，房间301，两瓶水。信息够了。
        → LLM 决定调用 request_supplies(room_number="301", item="矿泉水", quantity=2)

Step 2: 工具执行，返回 "已下单，预计10分钟送达"

Step 3: LLM 观察结果 → "好的先生，两瓶矿泉水马上送到301房间，大约10分钟。"
```

**2-3 步 vs 12 步。** 而且 LLM 自己判断"信息够不够"、"选哪个工具"、"怎么回复"——而不是代码替它判断。

---

## 五、真正的 Agent 循环：ReAct 模式

```
┌──────────────────────────────────────────┐
│                                          │
│  用户输入                                 │
│     ↓                                    │
│  ┌─────────┐                             │
│  │  LLM    │ ← 大脑：理解、推理、决策      │
│  │ (思考)   │                             │
│  └────┬────┘                             │
│       │                                   │
│       ├── 信息够了 → 调用工具              │
│       │       ↓                           │
│       │  ┌─────────┐                      │
│       │  │ 工具执行  │ ← 手：执行操作       │
│       │  └────┬────┘                      │
│       │       ↓                           │
│       │  观察结果 → 回到 LLM               │
│       │                                   │
│       ├── 信息不够 → 追问用户              │
│       │       ↓                           │
│       │  用户回复 → 回到 LLM               │
│       │                                   │
│       └── 任务完成 → 生成回复给用户         │
│                                          │
└──────────────────────────────────────────┘
```

这就是 **ReAct（Reasoning + Acting）** 模式。LangGraph 的 `ToolNode` 天然支持这种循环。

---

## 六、规则应该放在哪里？

不是说不要规则。规则要有，但位置要对：

| 规则类型 | 正确的位置 | 错误的位置 |
|----------|-----------|-----------|
| **内容安全**（政治/色情/暴力） | ✅ 代码前置过滤 | — |
| **业务边界**（我不负责点餐） | ✅ System Prompt 里描述 | ❌ 硬编码的意图映射表 |
| **工具选择**（该调哪个函数） | ✅ LLM 根据工具描述自行判断 | ❌ `INTENT_TOOL_MAP` 查表 |
| **信息完整性**（缺房间号要问） | ✅ LLM 自己判断 + 追问 | ❌ `slot_validator` 代码检查 |
| **工具参数格式**（房间号必须是3-4位数字） | ✅ 工具函数内部校验 | ✅ 可以保留 |
| **高风险操作确认**（产生费用/工单） | ✅ 工具描述中标注 + LLM判断何时确认 | ❌ 代码查 `risk_control.json` 强制确认 |

### 一句话总结：代码做安全底线，LLM 做业务决策。

---

## 七、我过度设计的地方

### ❌ 可以去掉或大幅精简的节点：

| 节点 | 问题 | 
|------|------|
| `slot_validator` | LLM 在输出 JSON 时就已经知道槽位对不对了，你用代码又校验了一遍 |
| `entity_resolver` | LLM 理解"301"就是房间号，不需要你查 Lexicon 表 |
| `capability_gate` | 能力边界写在 System Prompt 里就行，LLM 会自己判断"这不是我的范围" |
| `risk_checker` | 高风险确认可以让 LLM 在调工具前自己判断。工具描述里标注"此操作会产生费用，调用前请确认"就够了 |
| `clarify_builder` | LLM 自己就会追问，不需要代码构建追问结构 |
| `locale_resolver` | LLM 本身就能处理多语言，它会自动跟随用户的语言回复 |

### ❌ 不需要的配置文件：

| 文件 | 问题 |
|------|------|
| `intent_definitions.json` | 6 条 intent 写在 System Prompt 里就行 |
| `slot_definitions.json` | 槽位约束写在工具函数签名里就行 |
| `capability_matrix.json` | 能力边界写在 System Prompt 和工具描述里 |
| `risk_control.json` | 风险提示写在工具描述里 |

---

## 八、改造方向：从流水线到 Agent

### 改造后的 LangGraph 图（4-5 个节点）：

```
START
  │
  ▼
┌──────────────────┐
│ content_safety   │  ← 保留。内容安全是代码该做的事
│ (政治/暴力/色情)  │
└──────┬───────────┘
       │ SAFE              │ UNSAFE → refuse → END
       ▼
┌──────────────────┐
│ agent_loop       │  ← ★ 核心节点：LLM + bind_tools(ALL_TOOLS)
│ (LLM 自主决策)    │      LLM 在这里完成：意图理解、槽位提取、
│                  │      工具选择、追问判断、多轮循环
└──────┬───────────┘
       │
       ├── LLM 调了工具 → ToolNode 执行 → 回到 agent_loop
       │
       └── LLM 生成回复 → END
```

### 核心变化：

1. **LLM 直接绑工具**：用 `llm.bind_tools(ALL_TOOLS)` 替代 `response_format: json_object`
2. **ToolNode 标准循环**：用 LangGraph 自带的 `ToolNode` + 条件边实现 ReAct 循环
3. **System Prompt 替代配置文件**：意图定义、槽位要求、能力边界全部写在 prompt 里
4. **工具描述就是文档**：每个工具的 docstring 告诉 LLM 这个工具干什么、什么参数必填、什么场景用
5. **代码只做安全底线**：内容安全过滤 + 工具层面的参数格式校验

---

## 九、核心教训

1. **Agent 的核心是"自主决策"，不是"流水线处理"。** LLM 是大脑，代码是手和工具，不要让代码去替大脑做决策。

2. **信任 LLM 的判断力。** 它能理解"我那屋有点冷"需要追问房间号，不需要你写正则去匹配。

3. **用 System Prompt + 工具描述替代配置文件。** LLM 能从自然语言描述中理解约束，不需要你转成 JSON 规则表。

4. **规则只做兜底，不做决策。** 内容安全过滤是合理的兜底；工具参数格式校验是合理的兜底。但"这个意图应该调哪个工具"不应该由代码决定。

5. **少即是多。** 12 个节点的流水线看起来"很完整"，但实际上是过度工程化。好的 Agent 设计应该是简洁的循环，让 LLM 的智能充分发挥。

---

## 十、参考资料

- **ReAct 论文**：Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models" (2023)
- **LangGraph ReAct Agent 教程**：https://langchain-ai.github.io/langgraph/tutorials/introduction/
- **Anthropic 关于 Agent 的博客**："Building effective agents" — 强调简单的工作流而非复杂流水线

---

*笔记结束。下一步：思考具体怎么把 12 节点流水线改造成 4-5 节点的真正 Agent。*
