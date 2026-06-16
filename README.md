# 🏨 酒店客房服务 Agent v3

> **ReAct 模式智能体** — LLM 自主决策，本地 Ollama 运行，零外部依赖 RAG
>
> 从 v2 的 4 节点 DeepSeek 云 API 架构演进而来。信任 LLM 的判断力，精简工作流、去除冗余依赖、实现对话持久化。
>
> 🧩 **一套行业无关的 Agent 骨架** — 换掉 System Prompt 和工具函数，就能变成任何领域的智能助手。

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2-green)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688)](https://fastapi.tiangolo.com/)
[![Ollama](https://img.shields.io/badge/LLM-Ollama%20qwen3:8b-FF6B00)](https://ollama.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📌 v2 → v3 演进

| 维度 | v2 | v3 |
|---|---|---|
| **架构思想** | 4 节点 ReAct Agent (Safety→Logic→RAG→Agent) | **2 节点** ReAct Agent (RAG→Agent) |
| **LLM** | DeepSeek API (云端 deepseek-chat) | **Ollama 本地** (qwen3:8b) |
| **运行成本** | 按 Token 付费 | **零成本，本地运行** |
| **RAG 引擎** | Chroma + HuggingFace Embeddings (~90MB 下载) | **纯 Python TF-IDF**（零外部依赖） |
| **LLM 调用/请求** | 2-3 次（Safety + Logic + Agent） | **1 次**（Agent 一次性判断） |
| **State 字段** | 5 个 (messages/context/is_safe/logic_result/logic_note) | **2 个** (messages/context) |
| **对话持久化** | MemorySaver，重启即丢失 | **JSON 文件自动保存/恢复** |
| **安全检查** | 独立 LLM 安全节点 + 独立拒绝回复生成 | System Prompt 内置约束，Agent 自行判断 |
| **逻辑检查** | 独立 LLM 逻辑节点 + 独立引导回复生成 | Agent 自行判断，一次性处理 |
| **工具返回** | 结构化数据，LLM 自行组织语言 | 预写中文 message 字段，回复更稳定 |
| **房间号校验** | 无 | **`_check_room()`** 防 LLM 编造房间号 |
| **工具调用溯源** | API 响应无工具信息 | **ChatResponse 新增 tool_calls 字段** |
| **性能测试** | 无 | **`test_performance.py`** 6 维度自动化测试 |
| **代码行数** | ~500 行 | ~400 行 |
| **pip 依赖** | 需下载 ~90MB 嵌入模型 | 零额外下载，启动即用 |

### 架构对比

```
v2: START → Safety Check ──(SAFE)──→ Logic Check ──(valid)──→ RAG → Agent ⇄ Tools → END
              │(UNSAFE)                  │(invalid)
              ▼                          ▼
         safety_refuse              logic_guide
              │                          │
              └──────────► END ◄──────────┘
         （每次请求 2-3 次 LLM 调用）
         （LLM 同时做安全裁判 + 逻辑裁判 + 业务决策）
         （代码不信任 LLM，处处额外检查）

v3: START → RAG → Agent(LLM + 8 Tools) ⇄ Tools → END
                  ↑___________________________|
                    ReAct 自主循环
         （每次请求 1 次 LLM 调用）
         （安全/逻辑/业务全部由 Agent 在单次调用中判断）
         （信任 LLM，约束写在 System Prompt 里）
```

### 核心理念变化

> **v2 的问题**：代码不信任 LLM，替 LLM 做了太多判断。安全检查、逻辑检查都是独立的 LLM 调用 —— 既然最终还是靠 LLM 判断，为什么要调三次？既重复又慢。
>
> **v3 的答案**：LLM 是大脑，只调一次。安全边界、逻辑规则全部写进 System Prompt，Agent 在单次推理中同时判断安全、逻辑和业务意图。工作流从 4 步精简到 2 步，延迟减半。同时用 Ollama 本地运行 —— 零 API 成本、零网络延迟、数据不出本地。

---

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────┐
│                    ReAct Agent                       │
│                                                     │
│  ┌──────────┐              ┌───────────────────┐    │
│  │   RAG    │─────────────▶│   Agent (LLM)     │    │
│  │ 知识检索  │              │   + 8 Tools       │    │
│  └──────────┘              └────────┬──────────┘    │
│                                     │               │
│                        文本回复 ◄───┼──► 工具调用     │
│                                     │               │
│                            ┌────────▼──────────┐    │
│                            │  Tool Executor     │    │
│                            │  (8 mock tools)    │    │
│                            └───────────────────┘    │
└─────────────────────────────────────────────────────┘
```

### 2 个图节点

| 节点 | 职责 | 谁做决策 |
|---|---|---|
| **RAG** | 从酒店知识库检索相关信息（TF-IDF 向量检索），注入 System Prompt | 代码（知识增强） |
| **Agent** | 理解意图、判断安全/逻辑/信息完整性、决定追问/执行、选择工具、生成回复 | **LLM 自主** |
| **Tools** | 执行 8 个客房服务工具函数（含房间号校验），返回结果给 Agent | 代码（执行层） |

---

## 🔄 不只是酒店 — 一套通用的 Agent 模板

**这个项目的价值远不止客房服务。** 它的核心是一套 **领域无关的 ReAct Agent 骨架**，可以快速改造成任何行业的智能助手。

### 骨架 vs 皮肤

```
┌─────────────────────────────────────────────┐
│  皮肤（你只需要改这 3 层）                      │
│  ┌─────────────────────────────────────┐    │
│  │  1. System Prompt   → 换角色/换规则  │    │
│  │  2. 工具函数         → 换业务能力     │    │
│  │  3. 知识库          → 换领域知识     │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  骨架（不需要动，拿来即用）                      │
│  ┌─────────────────────────────────────┐    │
│  │  LangGraph 图编排    → RAG → Agent   │    │
│  │                       ⇄ Tools        │    │
│  │  ReAct 循环          → 自主决策/追问   │    │
│  │  FastAPI 服务器      → 生产级 API     │    │
│  │  多会话记忆          → JSON 持久化     │    │
│  │  TF-IDF RAG         → 零依赖检索     │    │
│  │  Web UI              → 聊天界面      │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

### 改造成其他 Agent 只需 3 步

| 步骤 | 改什么 | 工作量 | 示例（→ 客服 Agent） |
|---|---|---|---|
| **① 换人设** | `prompts/system_prompt.txt` | 5 分钟 | "你是电商客服专员，处理退换货和物流查询…" |
| **② 换工具** | `tools_api/mock_services.py` | 30 分钟 | `query_order()` `process_refund()` `check_logistics()` |
| **③ 换知识** | `knowledge/placeholder_info.txt` | 5 分钟 | 商品退换政策、运费标准、售后流程 |

### 什么不用动

- `room_service_agent.py` — 图的编排逻辑、ReAct 循环、LLM 调用、RAG 检索、JSON 持久化，**全部不需要改**
- `server.py` — FastAPI 路由、CORS、健康检查，**一行不改就能用**
- `test_performance.py` — 6 维度性能测试，换个模型自动适配

### 可以变成什么

| 行业 | Agent 类型 | 一句话改造 |
|---|---|---|
| 🛒 电商 | 客服 Agent | System Prompt 换成客服人设，工具换成查单/退款/物流 |
| 🏥 医疗 | 导诊 Agent | 工具换成科室查询/预约挂号/症状初筛，知识库放就诊指南 |
| 🏦 金融 | 理财顾问 Agent | 工具换成账户查询/风险评估/产品推荐 |
| 📚 教育 | 助教 Agent | 工具换成题库检索/学习进度/作业批改 |
| 🍔 餐饮 | 点餐 Agent | 工具换成菜单查询/下单/排队取号 |
| 🚗 出行 | 用车 Agent | 工具换成叫车/预估价格/行程规划 |
| 📦 物流 | 快递 Agent | 工具换成查件/下单/投诉 |
| 💼 企业 | IT 助手 Agent | 工具换成工单/权限申请/设备报修 |

### 关键设计原则

> **LLM 是大脑，代码只是手和脚。**
>
> 传统做法：每个新业务需求 → 写一堆 if-else 规则，永远追不上用户的花样提问。
>
> v3 更进一步：连安全和逻辑检查的 LLM 调用都省了 —— 全部写进 System Prompt，Agent 单次推理同时完成安全裁判 + 逻辑判断 + 业务决策 + 回复生成。
> 你的工作从「写规则 + 写检查器」变成了「写 System Prompt + 写工具」。

---

## 🛠️ 8 个客房服务工具

| 工具函数 | 用途 | 对应 BRD 意图 | 房间号校验 |
|---|---|---|---|
| `request_supplies` | 客房物品补给（毛巾、矿泉水、牙刷等） | SVC_ROOM_001 | ✅ |
| `request_cleaning` | 预约客房清洁打扫 | SVC_HK_001 | ✅ |
| `report_maintenance` | 设备故障报修（空调、马桶、WiFi 等） | SVC_HK_001 | ✅ |
| `request_laundry` | 洗衣/干洗/熨烫服务 | SVC_HK_001 | ✅ |
| `call_hotel` | 呼叫前台/转接人工服务 | SVC_CALL_001 | - |
| `set_wake_up_call` | 设置叫醒/唤醒闹钟 | ALARM_001 | ✅ |
| `delete_alarm` | 删除/取消闹钟（⚠️ 需二次确认） | ALARM_002 | - |
| `close_alarm` | 关闭正在响的闹钟（⚠️ 需二次确认） | ALARM_003 | - |

### 工具改进（v2 → v3）

- **房间号校验**：5 个需要房间号的工具新增 `_check_room()` 校验，拒绝空值/N/A/过长/纯字母，防止 LLM 幻觉编造
- **预写中文回复**：每个工具返回 `message` 字段（自然中文），Agent 直接使用，回复更稳定可控
- **工具描述精简**：docstring 压缩到一行，减少 System Prompt 长度，加快推理

---

## 🚀 快速开始

### 前置条件

- Python 3.10+
- [Ollama](https://ollama.com) 已安装

### 安装 & 运行

```bash
# 1. 克隆项目
git clone https://github.com/JosephHu04/hotel-room-service-agent-v2.git
cd hotel-room-service-agent-v2

# 2. 下载模型（首次，约 5GB）
ollama pull qwen3:8b

# 3. 安装依赖（零额外下载，秒装）
cd agent主体框架
pip install -r requirements.txt

# 4. 启动 Gradio 测试界面（推荐）
python room_service_agent.py
# 界面运行在 http://127.0.0.1:7860

# 5. 或启动 FastAPI 服务器（生产模式）
python server.py
# 服务运行在 http://127.0.0.1:8000
# API 文档: http://127.0.0.1:8000/docs
```

### 切换模型

编辑 `room_service_agent.py` 顶部配置：

```python
OLLAMA_BASE_URL = "http://localhost:11434/v1"   # Ollama 服务地址
OLLAMA_MODEL = "qwen3:8b"                       # 改成任意 Ollama 模型
# 推荐: qwen3:4b (更快) / qwen3:14b (更强) / llama3.1:8b / mistral:7b
```

### 使用前端 UI

用浏览器打开 `ui界面文件/chat_ui.html`（需先启动后端）。

```bash
# Windows
start "" ui界面文件\chat_ui.html

# macOS
open ui界面文件/chat_ui.html
```

### 运行性能测试

```bash
python test_performance.py
```

输出示例：

```
============================================================
  综合性能报告
============================================================
  模型: qwen3:4b (Ollama)
  RAG 检索速度:    2.3 ms
  端到端延迟:      平均 3.2s | 最快 1.5s | 最慢 5.8s
  Token 速度:      18 tok/s
  工具调用准确率:  100%
  边界拒绝准确率:  100%
  追问准确率:      100%
  安全拒绝准确率:  100%
  综合得分: 100%
============================================================
```

---

## 📡 API 接口

### `POST /api/chat` — 核心对话接口

```json
// Request
{
  "message": "送两瓶矿泉水到301",
  "session_id": "301"
}

// Response（v3 新增 tool_calls 字段）
{
  "response": "好的，两瓶矿泉水马上送到301，大概十分钟就到。",
  "session_id": "301",
  "tool_calls": [
    {"tool": "request_supplies", "args": {"room_number": "301", "item": "矿泉水", "quantity": 2}}
  ]
}
```

### `GET /api/health` — 健康检查

```json
{
  "status": "ok",
  "agent": "RoomServiceAgent",
  "model": "qwen3:8b (Ollama 本地)",
  "tools": ["request_supplies", "request_cleaning", "report_maintenance", "request_laundry", "call_hotel", "set_wake_up_call", "delete_alarm", "close_alarm"]
}
```

### `DELETE /api/sessions/{session_id}` — 清除会话（退房）

从内存和 `conversations.json` 文件同时删除，保护客人隐私。

---

## 📁 项目结构

```
hotel-agent-v3/
├── README.md                          ← 项目说明（中英双语）
├── .gitignore
│
├── agent主体框架/                      ← 核心代码
│   ├── room_service_agent.py          ★ Agent 主程序（ReAct 循环 + TF-IDF RAG + JSON 持久化）
│   ├── server.py                      ★ FastAPI 生产服务器
│   ├── requirements.txt               Python 依赖（精简，零额外下载）
│   ├── .env.example                   环境变量模板
│   ├── prompts/
│   │   └── system_prompt.txt          System Prompt（~70行，含安全/逻辑约束）
│   ├── knowledge/
│   │   └── placeholder_info.txt       酒店知识库（TF-IDF 检索源）
│   └── tools_api/
│       └── mock_services.py           8 个工具函数（含房间号校验 + 预写中文回复）
│
├── ui界面文件/                         ← 前端
│   └── chat_ui.html                   纯 HTML 聊天界面
│
├── Demand/                            ← 需求文档
│   ├── BRD_客房服务Agent提取.md
│   └── BRD全表.md
│
└── README/                            ← 设计文档
    ├── README.md
    ├── README_什么是真正的Agent.md
    ├── README_重构方案_从流水线到Agent.md
    └── README_重构执行清单.md
```

---

## 🔧 技术栈

| 组件 | 技术 | 说明 |
|---|---|---|
| **编排框架** | LangGraph 1.2 | 有向图编排，条件路由，ReAct 循环 |
| **LLM** | Ollama (qwen3:8b) | 本地运行，零成本，兼容 OpenAI 接口格式 |
| **记忆** | MemorySaver + JSON 文件 | 内存会话 + `conversations.json` 自动持久化，重启不丢失 |
| **RAG** | TF-IDF 纯 Python 实现 | 中文分词 + TF-IDF 向量化 + 余弦相似度，零外部依赖 |
| **后端** | FastAPI + Uvicorn | 异步高性能，自动生成 OpenAPI 文档 |
| **前端** | HTML + CSS + Vanilla JS | 零构建，浏览器直接打开 |
| **测试界面** | Gradio 6.x | 本地快速测试对话 |
| **性能测试** | 自研 6 维度套件 | RAG速度/延迟/Token速度/工具准确率/边界拒绝/追问率 |

### 技术栈变化（v2 → v3）

| 组件 | v2 | v3 | 变化 |
|---|---|---|---|
| **LLM** | DeepSeek Chat API | Ollama qwen3:8b | 云端→本地，按量付费→零成本 |
| **RAG** | Chroma + all-MiniLM-L6-v2 | TF-IDF 标准库 | 3个外部依赖→0个，~90MB下载→0 |
| **记忆** | MemorySaver | MemorySaver + JSON | 重启丢失→自动恢复 |
| **测试** | - | test_performance.py | 新增 6 维度自动化 |

---

## 🎯 对话示例

```
用户: 送两瓶矿泉水和一条毛巾到301
Agent: 🧠 TF-IDF检索"客房消耗品清单" → 决定调用 request_supplies
       好的，两瓶矿泉水和一条毛巾马上送到301，大概十分钟就到。

用户: 302的空调不制冷了，快来看看
Agent: 🧠 检索"报修常见问题分类" → 决定调用 report_maintenance(urgency="urgent")
       已经记录下来了，302房间的空调不制冷问题，维修师傅优先处理，马上到。

用户: 帮我预约明早7点的叫醒服务，房间503
Agent: 🧠 检索"叫醒服务" → 决定调用 set_wake_up_call
       已为房间503设置唤醒服务，时间：明早7:00。届时电话将自动振铃。

用户: 送瓶水过来
Agent: 🧠 缺房间号，不调工具 → 追问
       好的，请问您需要送到哪个房间呢？

用户: 帮我关灯
Agent: 🧠 System Prompt约束：设备控制→引导使用控制面板 → 不调工具
       抱歉，关灯需要使用您房间墙上的控制面板哦，那个我不方便远程操作。

用户: 帮我写诗
Agent: 🧠 System Prompt约束：非酒店话题 → 拒绝，不调工具
       抱歉先生/女士，我是您的酒店专属管家，仅为您解答酒店相关服务。
       如果有其他需要，随时叫我。
```

---

## ⚠️ 注意事项

- **API Key 安全**：`.env` 和 `conversations.json` 已在 `.gitignore` 中排除。使用 `.env.example` 作为模板，**切勿将真实 API Key 提交到代码仓库**。
- **Ollama 端口**：默认连接 `localhost:11434`。如果 Ollama 运行在其他端口，修改 `room_service_agent.py` 中的 `OLLAMA_BASE_URL`。
- **模型选择**：推荐 `qwen3:8b`（平衡质量与速度）。追求速度用 `qwen3:4b`，追求质量用 `qwen3:14b` 或 `llama3.1:8b`。
- **对话持久化**：`conversations.json` 会在 `agent主体框架/` 下自动生成。退房时 `DELETE /api/sessions/{id}` 会同步清除 JSON 中的数据。如需清理所有历史，直接删除该文件即可。
- **Mock 工具**：当前工具函数返回模拟数据。生产环境需对接真实的酒店 PMS 系统（替换 `mock_services.py` 中的函数实现即可，接口不变）。
- **TF-IDF 限制**：纯 Python 实现的检索精度略低于语义向量模型，但在酒店客房服务这个窄领域场景下影响极小。如果未来知识库超过 100 条，可换回 Chroma。

---

## 📄 License

MIT License

---

*Built with LangGraph · Ollama · FastAPI · Gradio*

---

> ————

# 🏨 Hotel Room Service Agent v3

> **ReAct Agent Pattern** — LLM as the autonomous brain, local Ollama runtime, zero-dependency RAG
>
> Evolved from v2's 4-node DeepSeek cloud API architecture. Trust the LLM's judgment — streamlined workflow, removed redundant dependencies, added conversation persistence.
>
> 🧩 **An industry-agnostic Agent skeleton** — swap the System Prompt and tool functions to turn it into an intelligent assistant for any domain.

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2-green)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688)](https://fastapi.tiangolo.com/)
[![Ollama](https://img.shields.io/badge/LLM-Ollama%20qwen3:8b-FF6B00)](https://ollama.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📌 v2 → v3 Evolution

| Dimension | v2 | v3 |
|---|---|---|
| **Paradigm** | 4-node ReAct (Safety→Logic→RAG→Agent) | **2-node** ReAct (RAG→Agent) |
| **LLM** | DeepSeek API (cloud, deepseek-chat) | **Ollama local** (qwen3:8b) |
| **Cost** | Pay per token | **Zero cost, local** |
| **RAG Engine** | Chroma + HuggingFace (~90MB download) | **Pure Python TF-IDF** (zero deps) |
| **LLM Calls/Request** | 2-3 (Safety + Logic + Agent) | **1** (Agent handles all) |
| **State Fields** | 5 | **2** |
| **Persistence** | MemorySaver, lost on restart | **JSON auto-save/restore** |
| **Safety Check** | Separate LLM call + rejection generator | System Prompt constraints, Agent self-judges |
| **Logic Check** | Separate LLM call + guidance generator | Agent self-judges in single pass |
| **Tool Return** | Structured data, LLM composes message | Pre-written Chinese message field |
| **Room Validation** | None | **`_check_room()`** anti-hallucination |
| **Tool Trace** | None | **ChatResponse includes `tool_calls`** |
| **Perf Testing** | None | **`test_performance.py`** 6-dimension suite |
| **Code Size** | ~500 lines | ~400 lines |
| **pip Deps** | ~90MB embedding model download | Zero extra downloads |

### Architecture Comparison

```
v2: START → Safety Check ──(SAFE)──→ Logic Check ──(valid)──→ RAG → Agent ⇄ Tools → END
              │(UNSAFE)                  │(invalid)
              ▼                          ▼
         safety_refuse              logic_guide
         (2-3 LLM calls per request)
         (Code doesn't trust the LLM — double-checks everything)

v3: START → RAG → Agent(LLM + 8 Tools) ⇄ Tools → END
         (1 LLM call per request)
         (Trust the LLM — constraints live in the System Prompt)
```

### Core Philosophy Shift

> **v2's problem**: The code didn't trust the LLM. Safety check = separate LLM call. Logic check = separate LLM call. If the LLM is ultimately making all these judgments anyway, why call it three times? Redundant and slow.
>
> **v3's answer**: The LLM is the brain — call it once. Safety boundaries and logic rules go into the System Prompt. The Agent judges safety, logic, and business intent all in a single inference. Two fewer nodes, half the latency. Plus Ollama local runtime — zero API cost, zero network delay, data stays on-prem.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                    ReAct Agent                       │
│                                                     │
│  ┌──────────┐              ┌───────────────────┐    │
│  │   RAG    │─────────────▶│   Agent (LLM)     │    │
│  │Knowledge │              │   + 8 Tools       │    │
│  └──────────┘              └────────┬──────────┘    │
│                                     │               │
│                        Text reply ◄──┼──► Tool call  │
│                                     │               │
│                            ┌────────▼──────────┐    │
│                            │  Tool Executor     │    │
│                            │  (8 mock tools)    │    │
│                            └───────────────────┘    │
└─────────────────────────────────────────────────────┘
```

### 2 Graph Nodes

| Node | Responsibility | Who Decides |
|---|---|---|
| **RAG** | TF-IDF vector search over hotel knowledge base, injects into System Prompt | Code (knowledge augmentation) |
| **Agent** | Understands intent, judges safety/logic/completeness, decides clarify/execute, picks tools, generates reply | **LLM autonomously** |
| **Tools** | Executes 8 room service tools (with room validation), returns structured results | Code (execution layer) |

---

## 🔄 Not Just a Hotel — A Universal Agent Template

**This project's value goes far beyond room service.** At its core is a **domain-agnostic ReAct Agent skeleton** that can be rapidly adapted into an intelligent assistant for any industry.

### Skeleton vs. Skin

```
┌─────────────────────────────────────────────┐
│  SKIN (only 3 layers to customize)           │
│  ┌─────────────────────────────────────┐    │
│  │  1. System Prompt   → Swap role/rules│   │
│  │  2. Tool functions   → Swap business │   │
│  │  3. Knowledge base   → Swap domain   │   │
│  └─────────────────────────────────────┘    │
│                                             │
│  SKELETON (ready to use, no changes needed)  │
│  ┌─────────────────────────────────────┐    │
│  │  LangGraph orchestration → RAG→Agent│    │
│  │                      ⇄ Tools         │    │
│  │  ReAct loop           → Auto-decide  │    │
│  │  FastAPI server       → Production API│   │
│  │  Multi-session memory → JSON persist  │    │
│  │  TF-IDF RAG           → Zero-deps     │    │
│  │  Web UI               → Chat interface│    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

### 3 Steps to Build a New Agent

| Step | What to Change | Effort | Example (→ Customer Service Agent) |
|---|---|---|---|
| **① Persona** | `prompts/system_prompt.txt` | 5 min | "You are an e-commerce support specialist handling returns and shipping…" |
| **② Tools** | `tools_api/mock_services.py` | 30 min | `query_order()` `process_refund()` `check_logistics()` |
| **③ Knowledge** | `knowledge/placeholder_info.txt` | 5 min | Return policies, shipping rates, after-sales procedures |

### What You Don't Touch

- `room_service_agent.py` — Graph orchestration, ReAct loop, LLM invocation, TF-IDF RAG, JSON persistence — **zero changes needed**
- `server.py` — FastAPI routes, CORS, health checks — **works out of the box**
- `test_performance.py` — 6-dimension perf tests, auto-adapts to new models

### What It Can Become

| Industry | Agent Type | In a Nutshell |
|---|---|---|
| 🛒 E-Commerce | Customer Service Agent | Tools for order lookup, refunds, logistics tracking |
| 🏥 Healthcare | Triage Agent | Tools for department lookup, appointment booking, symptom screening |
| 🏦 Finance | Advisory Agent | Tools for account inquiry, risk assessment, product recommendations |
| 📚 Education | Teaching Assistant | Tools for quiz retrieval, progress tracking, assignment grading |
| 🍔 Food & Beverage | Ordering Agent | Tools for menu browsing, ordering, queue management |
| 🚗 Mobility | Ride-Hailing Agent | Tools for booking, fare estimation, trip planning |
| 📦 Logistics | Parcel Agent | Tools for tracking, shipping, complaints |
| 💼 Enterprise | IT Helpdesk Agent | Tools for tickets, permissions, device repair |

### Key Design Principle

> **The LLM is the brain. Code is just the hands and feet.**
>
> Traditional approach: every new business requirement → a pile of if-else rules, forever chasing the endless variety of user queries.
>
> v3 goes further: even the safety and logic check LLM calls are eliminated — everything lives in the System Prompt. The Agent does safety judgment + logic validation + business decisions + reply generation all in a single inference.
> Your job shifts from "writing rules + writing checkers" to "writing System Prompts + writing tools".

---

## 🛠️ 8 Room Service Tools

| Tool Function | Purpose | BRD Intent | Room Validate |
|---|---|---|---|
| `request_supplies` | Deliver amenities (towels, water, toothbrushes) | SVC_ROOM_001 | ✅ |
| `request_cleaning` | Schedule housekeeping | SVC_HK_001 | ✅ |
| `report_maintenance` | Report equipment issues (AC, toilet, WiFi) | SVC_HK_001 | ✅ |
| `request_laundry` | Laundry / dry cleaning / ironing | SVC_HK_001 | ✅ |
| `call_hotel` | Transfer to front desk / human staff | SVC_CALL_001 | - |
| `set_wake_up_call` | Set wake-up / morning call alarm | ALARM_001 | ✅ |
| `delete_alarm` | Delete/cancel alarm (⚠️ confirm first) | ALARM_002 | - |
| `close_alarm` | Dismiss a ringing alarm (⚠️ confirm first) | ALARM_003 | - |

### Tool Improvements (v2 → v3)

- **Room validation**: 5 room-dependent tools now use `_check_room()` — rejects empty, N/A, too-long, non-numeric room numbers
- **Pre-written Chinese replies**: Each tool returns a `message` field with natural Chinese — more stable and controllable than LLM-composed text
- **Compact docstrings**: Tool descriptions compressed to one line — shorter System Prompt, faster inference

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed

### Install & Run

```bash
# 1. Clone the repo
git clone https://github.com/JosephHu04/hotel-room-service-agent-v2.git
cd hotel-room-service-agent-v2

# 2. Pull the model (first time, ~5GB)
ollama pull qwen3:8b

# 3. Install dependencies (zero extra downloads)
cd agent主体框架
pip install -r requirements.txt

# 4. Launch Gradio test UI (recommended)
python room_service_agent.py
# UI at http://127.0.0.1:7860

# 5. Or start FastAPI server (production)
python server.py
# Server at http://127.0.0.1:8000
# API docs: http://127.0.0.1:8000/docs
```

### Switch Models

Edit the config at the top of `room_service_agent.py`:

```python
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "qwen3:8b"     # Try: qwen3:4b (faster) / qwen3:14b (smarter) / llama3.1:8b
```

### Using the Web UI

Open `ui界面文件/chat_ui.html` in your browser (backend must be running first).

```bash
# Windows
start "" ui界面文件\chat_ui.html

# macOS
open ui界面文件/chat_ui.html
```

### Run Performance Tests

```bash
python test_performance.py
```

---

## 📡 API Reference

### `POST /api/chat` — Core Chat Endpoint

```json
// Request
{
  "message": "Send two bottles of water to room 301",
  "session_id": "301"
}

// Response (v3 adds tool_calls field)
{
  "response": "Sure, two bottles of water will be delivered to room 301 within 10 minutes.",
  "session_id": "301",
  "tool_calls": [
    {"tool": "request_supplies", "args": {"room_number": "301", "item": "water", "quantity": 2}}
  ]
}
```

### `GET /api/health` — Health Check

```json
{
  "status": "ok",
  "agent": "RoomServiceAgent",
  "model": "qwen3:8b (Ollama local)",
  "tools": ["request_supplies", "request_cleaning", "..."]
}
```

### `DELETE /api/sessions/{session_id}` — Clear Session (check-out)

Removes from both memory and `conversations.json` file.

---

## 📁 Project Structure

```
hotel-agent-v3/
├── README.md                          ← You are here (CN + EN)
├── .gitignore
│
├── agent主体框架/                      ← Core backend
│   ├── room_service_agent.py          ★ Agent main (ReAct loop + TF-IDF RAG + JSON persistence)
│   ├── server.py                      ★ FastAPI production server
│   ├── requirements.txt               Python deps (slim, zero extra downloads)
│   ├── .env.example                   Env config template
│   ├── prompts/
│   │   └── system_prompt.txt          System Prompt (~70 lines, safety + logic constraints)
│   ├── knowledge/
│   │   └── placeholder_info.txt       Hotel KB (TF-IDF source)
│   └── tools_api/
│       └── mock_services.py           8 tools (room validation + pre-written replies)
│
├── ui界面文件/                         ← Frontend
│   └── chat_ui.html                   Zero-build HTML chat interface
│
├── Demand/                            ← Requirements (Chinese)
│   ├── BRD_requirements.md
│   └── BRD_full_table.md
│
└── README/                            ← Design docs (Chinese)
    ├── what-is-an-agent.md
    ├── refactor-plan.md
    └── refactor-checklist.md
```

---

## 🔧 Tech Stack

| Component | Technology | Notes |
|---|---|---|
| **Orchestration** | LangGraph 1.2 | Directed graph, conditional routing, ReAct loop |
| **LLM** | Ollama (qwen3:8b) | Local, zero cost, OpenAI-compatible API |
| **Memory** | MemorySaver + JSON | In-memory sessions + `conversations.json` auto-persistence |
| **RAG** | TF-IDF Pure Python | Chinese tokenization + TF-IDF vectors + cosine similarity, zero deps |
| **Backend** | FastAPI + Uvicorn | Async, auto-generated OpenAPI docs |
| **Frontend** | HTML + CSS + Vanilla JS | Zero build, open in browser |
| **Test UI** | Gradio 6.x | Quick local chat testing |
| **Perf Testing** | Custom 6-dimension suite | RAG speed/latency/token speed/tool accuracy/boundary rejection/clarification |

### Tech Stack Changes (v2 → v3)

| Component | v2 | v3 | Change |
|---|---|---|---|
| **LLM** | DeepSeek Chat API | Ollama qwen3:8b | Cloud→Local, pay-per-token→free |
| **RAG** | Chroma + MiniLM | TF-IDF stdlib | 3 deps→0, ~90MB→0 download |
| **Memory** | MemorySaver | MemorySaver + JSON | Lost on restart→auto-restore |
| **Testing** | - | test_performance.py | New 6-dimension suite |

---

## 🎯 Conversation Examples

```
Guest: Send two bottles of water and a towel to 301
Agent: 🧠 TF-IDF search "amenity list" → decides request_supplies
       Sure, two bottles of water and a towel will be delivered to room 301
       right away, about 10 minutes.

Guest: The AC in 302 isn't cooling, come fix it now!
Agent: 🧠 Search "common maintenance issues" → decides report_maintenance(urgency="urgent")
       I've logged this — room 302 AC issue. A technician will be dispatched
       immediately as a priority.

Guest: Set a wake-up call for 7am tomorrow, room 503
Agent: 🧠 Search "wake-up service" → decides set_wake_up_call
       Wake-up call set for room 503 at 7:00 AM tomorrow.

Guest: Send a bottle of water
Agent: 🧠 Missing room number → asks, no tool call
       Sure, which room should I send it to?

Guest: Turn off the lights
Agent: 🧠 System Prompt: device control → guide to wall panel, no tool call
       Sorry, you'll need to use the control panel on the wall for the lights.

Guest: Write me a poem
Agent: 🧠 System Prompt: out of scope → refuses, no tool call
       I'm sorry, I'm your hotel service assistant. If you need other
       assistance, please call the front desk (ext. 0000).
```

---

## ⚠️ Important Notes

- **API Key Security**: `.env` and `conversations.json` are excluded via `.gitignore`. Use `.env.example` as a template — **never commit your real API key**.
- **Ollama Port**: Defaults to `localhost:11434`. Change `OLLAMA_BASE_URL` in `room_service_agent.py` if different.
- **Model Choice**: Recommended `qwen3:8b` (balanced). For speed use `qwen3:4b`, for quality use `qwen3:14b` or `llama3.1:8b`.
- **Persistence**: `conversations.json` auto-generates in `agent主体框架/`. Delete the file to clear all history. `DELETE /api/sessions/{id}` clears individual sessions from both memory and JSON.
- **Mock Tools**: Tool functions return simulated data. For production, replace the function bodies in `mock_services.py` — the interface stays the same.
- **TF-IDF Limitations**: Pure Python retrieval is slightly less precise than semantic embeddings, but negligible for this narrow hotel domain. If the knowledge base grows beyond ~100 entries, consider switching back to Chroma.

---

## 📄 License

MIT License

---

*Built with LangGraph · Ollama · FastAPI · Gradio*
