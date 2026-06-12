# 重构执行清单：从流水线到 Agent

> 按顺序执行，每完成一步打个勾。
> 预计总时间：6-8 小时

---

## 第〇步：准备工作（5分钟）

- [ ] 确认当前代码能跑通（`python room_service_agent.py` 不报错）
- [ ] 把整个 `agent主体框架/` 目录复制一份备份，叫 `agent主体框架_backup/`
- [ ] 确认 DeepSeek API Key 可用

---

## 第一步：删除 7 个 core/ 模块（2分钟）

> 这些文件全部不再需要，直接删除。

- [ ] 删除 `agent主体框架/core/slot_validator.py`（~510行，枚举/范围/必填校验）
- [ ] 删除 `agent主体框架/core/capability_gate.py`（~284行，能力矩阵门控）
- [ ] 删除 `agent主体框架/core/risk_checker.py`（~562行，风控红线检查）
- [ ] 删除 `agent主体框架/core/clarify_builder.py`（~460行，澄清追问模板）
- [ ] 删除 `agent主体框架/core/entity_resolver.py`（~82行，实体解析）
- [ ] 删除 `agent主体框架/core/locale_resolver.py`（~40行，语言检测）
- [ ] 删除 `agent主体框架/core/response_formatter.py`（~263行，输出格式化）

> 删除后 `core/` 目录应该为空，`core/` 目录也可以删掉。

**删除原因一句话**：LLM 自己会做这些事，不需要代码替它判断。

---

## 第二步：删除 5 个 config/ JSON（2分钟）

- [ ] 删除 `agent主体框架/config/intent_definitions.json`
- [ ] 删除 `agent主体框架/config/slot_definitions.json`
- [ ] 删除 `agent主体框架/config/capability_matrix.json`
- [ ] 删除 `agent主体框架/config/risk_control.json`
- [ ] 删除 `agent主体框架/config/general.json`

> 删除后 `config/` 目录可以删掉。

> ⚠️ `prompts/prompt_loader.py` 依赖这些 JSON，删了它也会报错。下一步统一处理。

---

## 第三步：清理 room_service_agent.py 内部（30分钟）

> 这是最大的一步。不删文件，而是删文件内部的代码段。

### 3.1 删除顶部的 import（约第 28-34 行）

```python
# ❌ 删除这些
from core.slot_validator import slot_validator_node
from core.capability_gate import capability_gate_node
from core.risk_checker import risk_checker_node, _is_confirm, _is_cancel
from core.clarify_builder import clarify_builder_node
from core.response_formatter import response_formatter_node
from core.locale_resolver import locale_resolver_node
from core.entity_resolver import entity_resolver_node
```

### 3.2 精简 State 定义（约第 50-84 行）

**删掉：**
```python
class State(TypedDict):
    """Agent 内部状态 — Day 6 扩展版"""
    # --- 原有字段 ---
    messages: Annotated[list, add_messages]
    context: str
    is_safe: str

    # ❌ 下面全部删掉
    raw_intents: list        # ❌
    raw_slots: dict          # ❌
    raw_entities: dict       # ❌
    analysis_json: str       # ❌
    need_clarify: bool       # ❌
    validated_slots: dict    # ❌
    decision_trace: list     # ❌
    confirm_pending: bool    # ❌
    confirm_action: dict     # ❌
    clarify_info: dict       # ❌
    result_type: str         # ❌
    structured_output: dict  # ❌
    locale: str              # ❌
    awaiting_slot: str       # ❌
    pending_intents: list    # ❌
    pending_slots: dict      # ❌
    skip_validation: bool    # ❌
```

**改成：**
```python
class State(TypedDict):
    messages: Annotated[list, add_messages]
    context: str       # RAG 检索上下文
    is_safe: str       # 护栏结果 SAFE / UNSAFE
```

### 3.3 删除工具→意图映射（约第 112-207 行）

**整个删掉：**
```python
# ❌ 全部删掉
TOOL_BY_NAME = {t.name: t for t in ALL_TOOLS}      # ❌
INTENT_TOOL_MAP = {...}                              # ❌
HOUSEKEEPING_TOOL_MAP = {...}                        # ❌
def determine_tool(intent, slots, entities): ...     # ❌ 整段函数删掉
```

### 3.4 删除 `chatbot_node` 并替换为 `agent_node`（约第 289-583 行）

**整个 `chatbot_node` 函数删掉**（约 300 行），替换为：

```python
def agent_node(state: State) -> dict:
    """
    ★ Agent 大脑节点。
    LLM 绑定全部工具，自己决定：理解意图 → 够不够信息 → 追问/调工具/直接回复。
    """
    sys_prompt = build_system_prompt(state.get("context", ""))

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

### 3.5 删除 `_safe_state` 函数（约第 605-603 行）

```python
# ❌ 整个函数删掉
def _safe_state(state: State) -> dict: ...
```

### 3.6 删除 `tool_executor_node` 函数（约第 605-669 行）

```python
# ❌ 整个函数删掉
def tool_executor_node(state: State) -> dict: ...
```

用 LangGraph 自带的 `ToolNode` 替代：
```python
from langgraph.prebuilt import ToolNode
# 在 build_graph 里直接用 ToolNode(ALL_TOOLS)
```

### 3.7 删除 3 个路由函数（约第 671-693 行）

```python
# ❌ 全部删掉
def check_after_chatbot(state: State) -> str: ...     # ❌
def check_after_validator(state: State) -> str: ...   # ❌
def should_continue_after_tools(state: State) -> str: ... # ❌
```

替换为一个：
```python
def should_continue(state: State) -> str:
    """检查最后一条消息是否有 tool_calls"""
    messages = state["messages"]
    last_msg = messages[-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "__end__"
```

### 3.8 重写 `build_graph()`（约第 699-770 行）

**整个函数替换为：**
```python
def build_graph():
    """构建 ReAct Agent 图 — 4 节点"""
    graph_builder = StateGraph(State)

    # 注册节点
    graph_builder.add_node("guardrail", guardrail_node)
    graph_builder.add_node("refuse", refuse_node)
    graph_builder.add_node("rag_retrieve", rag_node)
    graph_builder.add_node("agent", agent_node)
    graph_builder.add_node("tools", ToolNode(ALL_TOOLS))

    # 流转
    graph_builder.add_edge(START, "guardrail")
    graph_builder.add_conditional_edges(
        "guardrail", check_safety,
        {"refuse": "refuse", "retrieve": "rag_retrieve"}
    )
    graph_builder.add_edge("rag_retrieve", "agent")
    graph_builder.add_edge("refuse", END)

    # ★ ReAct 循环：agent ⇄ tools
    graph_builder.add_conditional_edges(
        "agent", should_continue,
        {"tools": "tools", "__end__": END}
    )
    graph_builder.add_edge("tools", "agent")

    return graph_builder
```

### 3.9 简化 `invoke_agent_structured`（约第 802-840 行）

这个函数依赖 `result_type`、`decision_trace`、`structured_output` 等已删除的 state 字段。
**可以直接删掉这个函数**，或者改成简单版本：
```python
def invoke_agent_structured(message: str, session_id: str = "default") -> dict:
    """对外统一调用接口 — 返回结构化输出。"""
    config = {"configurable": {"thread_id": session_id}}
    try:
        result = room_service_graph.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=config,
        )
        reply = result["messages"][-1].content
        return {
            "response_text": reply,
            "session_id": session_id,
        }
    except Exception as e:
        logger.error("会话[%s] 处理异常: %s", session_id, str(e))
        return {
            "response_text": "非常抱歉，系统暂时遇到了一些问题。请致电前台（电话：0000），我们的工作人员会立即为您处理。",
            "session_id": session_id,
        }
```

### 3.10 简化 `invoke_agent` 末尾日志

把约第 797 行的：
```python
logger.info("Agent 图编译完成 (Day 7: 10节点完整流水线 — clarify_builder + response_formatter)")
```
改成：
```python
logger.info("Agent 图编译完成 (ReAct: guardrail → RAG → agent ⇄ tools)")
```

---

## 第四步：重写 System Prompt（20分钟）

- [ ] 打开 `agent主体框架/prompts/system_prompt.txt`
- [ ] 清空全部内容
- [ ] 写入新的 prompt（见下方）

```
你是酒店客房服务管家，专门处理客人入住期间的客房相关需求。

【你的身份】
- 酒店专属管家，态度温和、礼貌、贴心
- 服务酒店前台电话：0000

【你可以做的事（通过调用工具）】
- 客房物品补给：送毛巾、矿泉水、牙刷、拖鞋、被子、枕头等
- 清洁打扫：安排保洁人员打扫房间
- 报修维护：灯泡、空调、马桶、WiFi、电视等故障报修
- 洗衣服务：干洗、水洗、熨烫
- 呼叫前台：帮客人转接前台/人工服务
- 叫醒服务：设置、取消、关闭叫醒闹钟

【你不能做的事】
如果客人问的不是你的职责范围，礼貌引导，不要尝试处理：
- 餐饮点餐（"有什么菜""点个套餐""送份早餐"）→ 引导去点餐服务
- 设备控制（"关灯""开空调""拉窗帘""调温度"）→ 引导使用房间控制面板
- 酒店设施问询（"早餐几点""泳池开到几点""WiFi密码多少"）→ 引导联系前台0000
- 周边推荐/旅游/叫车 → 引导联系礼宾部
- 入住/退房/换房/账单 → 引导去前台
- 非酒店话题（政治/代码/闲聊/写文章）→ 礼貌说明无法处理

【你的工作方式】
1. 理解客人说的话，判断是否在你的职责范围
2. 信息够了 → 调用对应的工具函数执行
3. 信息不够（缺房间号、缺时间、缺具体内容）→ 温和追问，不要猜
4. 高风险操作（删除闹钟、关闭闹钟）→ 先跟客人确认，客人回复"确认"/"好的"后再执行

【回复风格 —— 非常重要】
- 简短、自然、口语化，适合语音播报
- 亲切有温度，像真正的管家在说话
- 不要用括号、编号、Markdown、技术术语
- 好的示例："好的，矿泉水马上送到301，大概十分钟就到。"
- 坏的示例："已为您安排配送服务。物品：矿泉水x2，房间号：301，预估送达时间：10分钟。"

【默认值 —— 客人没说就按这个来】
- 数量没说 → 默认 1
- 打扫时间没说 → 默认"现在"
- 优先度没说 → 默认 normal（普通）
- 洗衣取件时间没说 → 默认"现在"

【安全边界】
- 绝不自己编造房间号
- 绝不执行明显危险的操作（如"把门锁打开"）
- 遇到骚扰/暴力/色情/政治内容 → 礼貌拒绝，引导联系前台
```

- [ ] 保存

### 同时处理 prompt_loader.py

- [ ] 打开 `agent主体框架/prompts/prompt_loader.py`
- [ ] **两种选择**：
  - **选 A（推荐）**：删掉这个文件，`room_service_agent.py` 里直接读 `system_prompt.txt`
  - **选 B**：保留文件，但删掉 `_load_json`、`_format_intent_table`、`_format_slot_table`、`_format_tool_rules`、`_build_json_output_instruction` 这些函数，`load_system_prompt()` 改成直接读 txt 文件拼接 RAG 上下文

推荐选 A，删掉 prompt_loader.py，在 `room_service_agent.py` 里加一个简单函数：

```python
def build_system_prompt(rag_context: str = "") -> str:
    """加载 System Prompt，附加 RAG 上下文"""
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read()
    if rag_context:
        prompt += f"\n\n【酒店知识库参考】\n{rag_context}"
    return prompt
```

---

## 第五步：处理 main_router.py 的兼容（10分钟）

`main_router.py` 目前 import 的是：
```python
from room_service_agent import room_service_graph as room_graph
```

只要 `room_service_agent.py` 里还 export `room_service_graph`，`main_router.py` **不需要改**。

- [ ] 确认 `room_service_agent.py` 底部有：`room_service_graph = build_graph().compile(checkpointer=agent_memory)`
- [ ] 确认 `main_router.py` 能正常 import

---

## 第六步：更新 server.py（如果有，5分钟）

- [ ] 检查 `agent主体框架/server.py`
- [ ] 如果有 `ChatResponse` 模型用了旧结构，精简它

---

## 第七步：测试（1小时）

### 7.1 启动测试

- [ ] 终端运行 `python room_service_agent.py`，看有没有报错
- [ ] Gradio 界面能正常打开

### 7.2 5 条核心测试

| # | 输入 | 期望行为 |
|---|------|---------|
| 1 | "送两瓶矿泉水和一条毛巾到301" | LLM 调 `request_supplies(room_number="301", item="两瓶矿泉水和一条毛巾")`，然后自然回复 |
| 2 | "302空调不制冷了，快来看看" | LLM 调 `report_maintenance(room_number="302", issue="空调不制冷", urgency="urgent")`，然后自然回复 |
| 3 | "帮我订个闹钟" | LLM 追问："请问您需要几点的叫醒呢？还有您的房间号是？" |
| 4 | "你好" | LLM 直接回复问候，不调任何工具 |
| 5 | "帮我取消所有闹钟" | LLM 先确认："好的，我帮您取消闹钟，确认吗？"（不调工具） |

### 7.3 3 条边界测试

| # | 输入 | 期望行为 |
|---|------|---------|
| 6 | "有什么好吃的推荐" | LLM 引导去点餐服务，不调工具 |
| 7 | "帮我关灯" | LLM 引导用房间控制面板，不调工具 |
| 8 | "我那屋有点冷" | LLM 理解这是在说房间问题，追问房间号 |

---

## 完成后的文件清单

```
agent主体框架/
├── room_service_agent.py      ← 重写（~250行）
├── main_router.py             ← 不改
├── server.py                  ← 轻改
├── requirements.txt           ← 不改
├── .env                       ← 不改
├── prompts/
│   └── system_prompt.txt      ← 重写（~60行）
├── tools_api/
│   └── mock_services.py       ← 不改（8个工具保留）
├── knowledge/
│   └── placeholder_info.txt   ← 不改
├── core/                      ← 空目录，可删
├── config/                    ← 空目录，可删
└── tests/
    └── test_room_service.py   ← 待重写
```

---

## 如果某一步出问题，怎么回退？

```
1. 删掉 agent主体框架/
2. 把 agent主体框架_backup/ 重命名回 agent主体框架/
3. 恢复完成
```

---

*准备好了就开始第一步：删 core/ 文件。*
