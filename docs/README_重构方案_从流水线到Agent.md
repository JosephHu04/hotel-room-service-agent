# 重构方案：从流水线到真正的 Agent

> 写于 2026-06-11
> 配套阅读：[README_什么是真正的Agent.md](README_什么是真正的Agent.md) — 先理解"为什么错"，再看"怎么改"

---

## 〇、现状 vs 目标 一图对比

### 现状：12 节点流水线

```
START → guardrail → locale_resolver → RAG → chatbot(LLM输出JSON)
→ slot_validator → entity_resolver → capability_gate → risk_checker
→ tool_executor → clarify_builder → response_formatter → END
```

- LLM 只是其中一个节点，用来输出 JSON
- 其余 9 个节点都是 Python 规则代码
- 代码替 LLM 做所有决策

### 目标：4 节点 ReAct Agent

```
START → content_safety → agent(LLM + bind_tools) ⇄ tools(ToolNode) → END
                              ↑___________________________|
                                ReAct 循环（LLM 自主决策）
```

- LLM 是整个系统的"大脑"
- 代码只做两件事：安全底线 + 提供工具
- LLM 自己决定：理解意图 → 够不够信息 → 追问还是调工具 → 选哪个工具 → 观察结果 → 下一步

---

## 一、保留清单（这些东西有价值，不删）

| 文件 | 保留理由 | 需要的改动 |
|------|---------|-----------|
| `tools_api/mock_services.py` | 8 个工具函数是 agent 的"手"，核心资产 | **轻改**：docstring 就是 LLM 的工具描述，需润色 |
| `main_router.py` | 5 路分发架构合理，先分流再交给子 agent | **不改** |
| `prompts/system_prompt.txt` | 角色定位文本保留 | **重写**：去掉 JSON 输出要求，加入工具使用指引 |
| `prompts/prompt_loader.py` | 动态加载 prompt 的机制保留 | **轻改**：不再加载 intent/slot JSON |
| `knowledge/placeholder_info.txt` | 酒店知识库 | **不改** |
| RAG 检索器 (`get_rag_retriever`) | 知识检索有用 | **不改**，知识注入 system prompt |
| `content_safety` 护栏 | 政治/色情/暴力过滤是代码该做的事 | **不改** |
| `MemorySaver` | 多会话记忆 | **不改** |

---

## 二、删除清单（这些东西在限制 LLM，应该砍掉）

### 2.1 整个文件删除

| 文件 | 行数 | 原来做什么 | 为什么删 |
|------|------|-----------|---------|
| `core/slot_validator.py` | ~510 行 | 枚举/范围/必填/格式校验 | LLM 自己判断信息够不够、格式对不对 |
| `core/capability_gate.py` | ~284 行 | 查能力矩阵，拦截不支持的意图 | 写在 system prompt 和工具描述里，LLM 自己判断 |
| `core/risk_checker.py` | ~562 行 | Intent 级风险 + GR-01~10 红线 | **部分保留**：二次确认逻辑改为 agent 循环中的一个轻量判断 |
| `core/clarify_builder.py` | ~460 行 | 用模板构建追问文本 | LLM 自己就会追问，不需要模板 |
| `core/response_formatter.py` | ~263 行 | 组装 FinalOutput JSON | 大幅简化，agent 的输出就是最终输出 |
| `core/entity_resolver.py` | ~82 行 | 查 Lexicon 表解析实体 | LLM 理解"301"就是房间号 |
| `core/locale_resolver.py` | ~40 行 | 检测用户语言 | LLM 自动跟随用户语言回复 |

**小计：约 2,200 行代码可以删除。**

### 2.2 配置文件删除

| 文件 | 原来做什么 | 为什么删 |
|------|-----------|---------|
| `config/intent_definitions.json` | 6 条意图的枚举定义 | 意图描述写在 system prompt 里 |
| `config/slot_definitions.json` | 11 个槽位的类型/范围/枚举 | 槽位约束写在工具函数的参数和 docstring 里 |
| `config/capability_matrix.json` | 设备-意图能力矩阵 | 能力边界写在 system prompt 里 |
| `config/risk_control.json` | 意图风险等级 + GR-01~10 | ⚠️ 二次确认逻辑轻量化保留 |
| `config/general.json` | 语言/设备类型枚举 | 不需要了 |

### 2.3 `room_service_agent.py` 内部删除

| 代码段 | 原来做什么 |
|--------|-----------|
| `INTENT_TOOL_MAP` 字典 | 意图→工具硬编码映射 |
| `HOUSEKEEPING_TOOL_MAP` 字典 | housekeeping 子类型→工具映射 |
| `determine_tool()` 函数 | 代码查表决定调哪个工具 |
| `_safe_state()` 函数 | 从 state 提取字段的胶水代码 |
| `tool_executor_node()` 函数 | 手动构造参数+调用工具 |
| `check_after_chatbot()` | 路由：解析成功→校验 / 失败→结束 |
| `check_after_validator()` | 路由：校验通过→执行 / 不通过→追问 |
| `should_continue_after_tools()` | 工具执行完→结束 |
| `chatbot_node` 中的追问补全逻辑 | `awaiting_slot`、`pending_intents` 等 ~80 行 |
| `chatbot_node` 中的确认/取消判断 | `_is_confirm`/`_is_cancel` 逻辑 |
| `chatbot_node` 中的口语剥离 | `_clean_msg` 逻辑 |
| `chatbot_node` 中的关键信息检查 | 用正则和 if-else 判断缺不缺房间号 |
| `chatbot_node` 中的超短消息快速响应 | ≤2 字符的特殊处理 |
| `llm_json` 实例 | `response_format: json_object` 不再需要 |
| State 中 15+ 个字段的大部分 | 精简到 5-6 个 |

---

## 三、改造后的 `room_service_agent.py` 长什么样

### 3.1 新的 State（从 15+ 字段精简到 5 个）

```python
class State(TypedDict):
    messages: Annotated[list, add_messages]  # 对话历史（LangGraph 自动管理）
    context: str                              # RAG 检索上下文
    is_safe: str                              # 护栏结果 SAFE / UNSAFE
```

就三个字段。不再需要 `raw_intents`、`raw_slots`、`validated_slots`、`need_clarify`、`confirm_pending`、`decision_trace`…… 这些全部由 LLM 在对话中自然管理。

### 3.2 新的节点（从 12 个精简到 4 个）

```python
def build_graph():
    graph_builder = StateGraph(State)

    # 节点 1：安全护栏（保留）
    graph_builder.add_node("guardrail", guardrail_node)

    # 节点 2：RAG 检索（保留，注入知识）
    graph_builder.add_node("rag", rag_node)

    # 节点 3：★ 核心 — Agent 节点（LLM + 工具）
    # 替代原来的 chatbot + slot_validator + entity_resolver +
    #         capability_gate + risk_checker + clarify_builder
    graph_builder.add_node("agent", agent_node)

    # 节点 4：工具执行（LangGraph 标准 ToolNode）
    graph_builder.add_node("tools", ToolNode(ALL_TOOLS))

    # ─── 流转 ───
    graph_builder.add_edge(START, "guardrail")
    graph_builder.add_conditional_edges("guardrail", check_safety,
        {"refuse": "refuse_node", "retrieve": "rag"})
    graph_builder.add_edge("rag", "agent")

    # ★ ReAct 循环：agent → tools → agent → ... → END
    graph_builder.add_conditional_edges("agent", should_continue,
        {"tools": "tools", "__end__": END})
    graph_builder.add_edge("tools", "agent")  # 工具结果回到 agent

    return graph_builder.compile(checkpointer=MemorySaver())
```

### 3.3 核心变化：agent_node

```python
def agent_node(state: State) -> dict:
    """
    ★ 整个 Agent 的大脑。
    
    LLM 绑定了所有工具，自己决定：
    - 理解意图
    - 信息够不够（要不要追问）
    - 选哪个工具
    - 什么时候确认
    - 怎么回复
    """
    sys_prompt = build_system_prompt(state.get("context", ""))

    # 关键：llm.bind_tools(ALL_TOOLS) — LLM 自己输出 tool_call
    llm_with_tools = ChatOpenAI(
        model="deepseek-chat",
        temperature=0.5,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
    ).bind_tools(ALL_TOOLS)

    messages = [SystemMessage(content=sys_prompt)] + state["messages"]
    response = llm_with_tools.invoke(messages)

    return {"messages": [response]}
```

就这么短。LLM 返回的可能是：
- 一个 `AIMessage`（直接回复用户，对话结束）
- 一个 `AIMessage` + `tool_calls`（需要调工具，继续循环）

### 3.4 路由逻辑：should_continue

```python
def should_continue(state: State) -> str:
    """检查最后一条消息是否有 tool_calls"""
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "__end__"
```

### 3.5 新的 System Prompt 核心结构

```markdown
你是酒店客房服务管家。你有以下工具：

1. request_supplies(room_number, item, quantity) — 送物品到房间
2. request_cleaning(room_number, time_preference) — 安排打扫
3. report_maintenance(room_number, issue, urgency) — 报修
4. request_laundry(room_number, items, pickup_time) — 洗衣服务
5. call_hotel(room_number) — 呼叫前台
6. set_wake_up_call(room_number, time) — 设置叫醒
7. delete_alarm(label, room_number) — 删除闹钟（⚠️ 需确认）
8. close_alarm(room_number, label) — 关闭闹钟（⚠️ 需确认）

【你的工作方式】
- 理解客人说的话，判断属于哪种需求
- 信息够了就调工具，信息不够就温和追问
- 高风险操作（delete_alarm、close_alarm）先跟客人确认再执行
- 不是你的范围（点餐/设备控制/周边推荐）礼貌说明并引导

【你不负责的】
- 点餐→引导去点餐服务
- 设备控制（关灯/开空调）→引导用房间面板
- 酒店设施问询（早餐几点/WiFi密码）→引导联系前台

【回复风格】
- 亲切、自然、口语化（适合语音播报）
- 简短，不要太长
- 不要用括号、编号、技术术语
```

对比你原来那个从 5 个 JSON 文件拼出来的巨型 prompt，这个简洁得多。**工具描述本身就是最好的"意图定义"和"槽位定义"。**

---

## 四、二次确认怎么处理？（最常被问的问题）

原方案用 `risk_checker.py` 的 562 行代码处理确认流程。Agent 方案怎么做？

### 方式：工具描述 + LLM 判断

只需在工具的 docstring 中标注：

```python
@tool
def delete_alarm(label: str, room_number: str = "") -> dict:
    """
    删除/取消闹钟。
    
    ⚠️ 重要：调用此工具前，必须先向客人确认是否真的要删除。
    确认话术示例："好的，我帮您取消'{label}'这个闹钟，确认吗？"
    客人回复"确认"/"好的"之后再调用此工具。
    
    Args:
        label: 闹钟标签
        room_number: 房间号
    """
```

LLM 看到这个描述后，自然会：
1. 客人说"取消闹钟" → LLM 想："哦，这个工具需要先确认" → 生成确认文本 → 不调工具
2. 客人说"确认" → LLM 想："好，客人确认了" → 调用 `delete_alarm`

**不需要一行确认/取消的关键词匹配代码。** LLM 理解"确认"、"好的"、"行"、"嗯"、"yes"、"OK"……比你写的关键词列表全面得多。

---

## 五、分步实施计划

### 第 1 步：新 Agent 原型（2-3 小时）

**目标**：跑通最简 ReAct 循环，验证"LLM 自主决策"可行。

**操作**：
1. 在 `room_service_agent.py` 同级新建 `room_service_agent_v2.py`
2. 实现 4 节点图：guardrail → rag → agent(bind_tools) ⇄ tools
3. 写新的 system prompt（不用 JSON 配置文件）
4. 用 Gradio 测试 5 条典型对话

**验收**：
- "送两瓶水到301" → LLM 自己调 `request_supplies`
- "打扫302" → LLM 自己调 `request_cleaning`
- "帮我订个闹钟" → LLM 追问几点
- "你好" → LLM 直接回复，不调工具
- "取消我所有的闹钟" → LLM 先确认再调 `delete_alarm`

### 第 2 步：对齐原功能（2-3 小时）

逐个对照原方案的功能，确认 Agent 方案都能覆盖：

| 原功能 | Agent 方案覆盖方式 |
|--------|-------------------|
| 意图识别 | LLM 阅读工具描述 + system prompt，自己判断 |
| 槽位提取 | LLM 从用户消息中提取，填入工具参数 |
| 枚举校验 | 工具函数的 docstring 描述合法值 |
| 必填检查 | 工具函数的参数定义（required vs optional） |
| 能力边界 | system prompt 说明"你不负责"的范围 |
| 二次确认 | 工具 docstring 标注 ⚠️ 需确认 |
| 多语言 | LLM 原生支持，自动跟随用户语言 |
| RAG 知识库 | 保留，注入 system prompt |

### 第 3 步：清理旧代码（1 小时）

1. 将 `room_service_agent_v2.py` 重命名为 `room_service_agent.py`
2. 删除 7 个不再需要的 `core/` 文件
3. 删除 `config/` 目录（或保留作为参考文档）
4. 更新 `main_router.py` 的 import（接口不变）

### 第 4 步：测试 & 打磨（2-3 小时）

1. 用原方案的 4 条 Example 测试
2. 边缘情况测试：
   - "我那屋有点冷" → LLM 应该追问房间号
   - "帮我关灯" → LLM 应该引导去控制面板
   - "有什么好吃的" → LLM 应该引导去点餐服务
   - 客人取消操作 → LLM 应该理解"算了"、"不用了"
3. 多轮对话测试（连续 3-5 轮）

---

## 六、代码量对比

| 维度 | 原方案 | Agent 方案 | 变化 |
|------|--------|-----------|------|
| `room_service_agent.py` | ~880 行 | ~200 行 | -77% |
| `core/` 模块 | 7 个文件, ~2,200 行 | 0 个文件 | -100% |
| `config/` JSON | 5 个文件 | 0 个文件 | -100% |
| System Prompt | ~300 行（动态拼接） | ~50 行（手写） | -83% |
| State 字段 | 15+ 个 | 3 个 | -80% |
| 图节点 | 12 个 | 4 个 | -67% |
| **总计** | **~3,400 行** | **~250 行** | **-93%** |

---

## 七、你可能会担心的问题 & 回答

### Q1: "没有 slot_validator，LLM 提取的房间号格式不对怎么办？"

**A**: 校验放在工具函数内部。`request_supplies(room_number)` 的第一行就可以 `if not re.match(r'^\d{3,4}$', room_number): return {"error": "房间号格式不对"}`。工具返回 error 后，LLM 看到错误信息自然会追问客人。这叫 **工具层面的校验**，不是流水线层面的校验。

### Q2: "没有 capability_gate，客人说'关灯'怎么办？"

**A**: System prompt 写明"你不负责设备控制，引导客人用房间面板"。LLM 理解这句话的能力比你写的 capability_matrix.json 强得多——它不需要你枚举所有"不支持"的情况。

### Q3: "没有 risk_checker，重要操作不确认怎么办？"

**A**: 工具 docstring 里标注 ⚠️。LLM 看到"调用此工具前必须先确认"就会照做。如果不放心，可以在 `delete_alarm` 和 `close_alarm` 函数内部加一个 `require_confirmation` 标记，在 agent_node 里做一道轻量检查——但大概率不需要。

### Q4: "LLM 有时候不稳定，输出不靠谱怎么办？"

**A**: 这才是关键心态转变。你的流水线方案假设"LLM 不可靠，需要规则兜底"，代价是 3,400 行代码。Agent 方案假设"LLM 基本可靠，只在必要处兜底"，代码量降到 250 行。**当 LLM 出错时，改进 prompt 和工具描述，比加一条规则更有效。** 这是为什么 Anthropic 和 LangChain 都在推"prompt-driven agent"而不是"rule-driven pipeline"。

### Q5: "我的 BRD 文档里那些配置表怎么办？"

**A**: BRD 的配置表是**需求文档**，不是**实现方案**。它们描述了"这个系统需要支持什么"，但实现方式可以是 JSON 规则引擎，也可以是一个好的 System Prompt + 工具描述。后者更灵活、更好维护。

---

## 八、重构后的完整图（最终态）

```
                        ┌─────────────┐
                        │  用户输入    │
                        └──────┬──────┘
                               │
                        ┌──────▼──────┐
                        │  guardrail  │  ← 保留：政治/色情/暴力过滤
                        │  (安全护栏)  │
                        └──────┬──────┘
                               │ SAFE
                        ┌──────▼──────┐
                        │     RAG     │  ← 保留：检索酒店知识
                        │  (知识检索)  │
                        └──────┬──────┘
                               │
                    ┌──────────▼──────────┐
                    │                     │
                    │   ★ agent_node ★    │  ← LLM + bind_tools(8个工具)
                    │   (大脑：理解+决策)   │
                    │                     │
                    └──────────┬──────────┘
                               │
                    LLM 判断：要不要调工具？
                               │
                    ┌──────────┴──────────┐
                    │                     │
                    ▼                     ▼
            ┌──────────────┐      ┌──────────────┐
            │  ToolNode    │      │    END       │
            │  (执行工具)   │      │  (直接回复)   │
            └──────┬───────┘      └──────────────┘
                   │
                   │ 工具结果
                   ▼
           回到 agent_node（观察结果 → 回复/再调工具）
```

**这就是一个真正的 Agent。** 循环简单、代码少、LLM 充分发挥智能。

---

## 九、开始重构的 Checklist

- [ ] 阅读并理解本文档
- [ ] 阅读配套 [README_什么是真正的Agent.md](README_什么是真正的Agent.md)
- [ ] **第 1 步**：创建 `room_service_agent_v2.py`，实现 4 节点原型
- [ ] **第 1 步**：写新的 system prompt（~50 行）
- [ ] **第 1 步**：Gradio 测试 5 条典型对话
- [ ] **第 2 步**：对照原功能清单逐项验证
- [ ] **第 2 步**：在工具 docstring 中标注 ⚠️ 高风险操作
- [ ] **第 3 步**：替换旧文件，清理 core/ 和 config/
- [ ] **第 3 步**：更新 main_router.py 的 import
- [ ] **第 4 步**：边缘情况测试
- [ ] **第 4 步**：多轮对话测试

---

*准备好了就开始第 1 步：创建 Agent 原型。*
