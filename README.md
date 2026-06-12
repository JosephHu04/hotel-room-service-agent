# 🏨 酒店客房服务 Agent v2

> **ReAct 模式智能体** — LLM 作为大脑自主决策，4 节点 LangGraph 架构
>
> 从 v1 的 12 节点流水线重构而来，删除 ~2,200 行规则代码，让 LLM 从"工具人"变成"决策者"。
>
> 🧩 **一套行业无关的 Agent 骨架** — 换掉 System Prompt 和工具函数，就能变成任何领域的智能助手。

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2-green)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688)](https://fastapi.tiangolo.com/)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek%20Chat-536DFE)](https://platform.deepseek.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📌 v1 → v2 演进

| 维度 | v1（旧架构） | v2（新架构） |
|---|---|---|
| **架构思想** | 帧基对话系统 (Frame-based DSL) | ReAct Agent (LLM 自主决策) |
| **图节点** | 12 个（含 7 个规则代码节点） | **4 个**（Guard → RAG → Agent ⇄ Tools） |
| **代码行数** | ~3,000 行 | ~500 行 |
| **LLM 角色** | 只是 JSON 提取器 | **系统的决策大脑** |
| **意图识别** | 代码硬编码映射表 | LLM 自主理解 |
| **槽位校验** | Python 规则（~510 行） | LLM 自行判断信息完整性 |
| **追问生成** | 模板拼接 | LLM 自然语言追问 |
| **工具选择** | `INTENT_TOOL_MAP` 查表 | LLM 自主选择最合适的工具 |
| **决策透明度** | 黑盒规则链 | ReAct 循环每步可追溯 |

### 架构对比

```
v1: START → Guard → Locale → RAG → LLM(JSON) → SlotValidate → EntityResolve
           → CapabilityGate → RiskCheck → ToolExecute → ClarifyBuild
           → ResponseFormat → END
           （LLM 只是中间一个节点）

v2: START → Guard → RAG → Agent(LLM + 8 Tools) ⇄ Tools → END
                          ↑___________________________|
                            ReAct 自主循环
                            （LLM 是整个系统的大脑）
```

### 核心理念变化

> **v1 的问题**：代码不信任 LLM，处处替 LLM 做决策。每增加一条规则就多一个盲点。
>
> **v2 的答案**：LLM 是大脑，代码只做两件事 — 安全底线 + 提供工具。LLM 自己理解意图、判断信息够不够、追问还是执行、选哪个工具、观察结果后决定下一步。

---

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────┐
│                    ReAct Agent                       │
│                                                     │
│  ┌──────────┐    ┌──────────┐    ┌───────────────┐  │
│  │  Guard   │───▶│   RAG    │───▶│  Agent (LLM)  │  │
│  │ 安全护栏  │    │ 知识检索  │    │  + 8 Tools    │  │
│  └──────────┘    └──────────┘    └───────┬───────┘  │
│                                          │          │
│                             文本回复 ◄───┼──► 工具调用│
│                                          │          │
│                                 ┌────────▼───────┐  │
│                                 │  Tool Executor  │  │
│                                 │  (8 mock tools) │  │
│                                 └────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 4 个图节点

| 节点 | 职责 | 谁做决策 |
|---|---|---|
| **Guard** | 敏感词过滤（政治/暴力/色情等），命中则直接拒绝 | 代码（安全底线） |
| **RAG** | 从酒店知识库检索相关信息，注入 System Prompt | 代码（知识增强） |
| **Agent** | 理解意图、判断信息完整性、决定追问/执行、选择工具、生成回复 | **LLM 自主** |
| **Tools** | 执行 8 个客房服务工具函数，返回结果给 Agent | 代码（执行层） |

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
│  │  LangGraph 图编排    → Guard → RAG   │    │
│  │                       → Agent ⇄ Tools│    │
│  │  ReAct 循环          → 自主决策/追问   │    │
│  │  FastAPI 服务器      → 生产级 API     │    │
│  │  多会话记忆          → 按用户隔离      │    │
│  │  安全护栏            → 敏感词过滤     │    │
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

- `room_service_agent.py` — 图的编排逻辑、ReAct 循环、LLM 调用，**全部不需要改**
- `server.py` — FastAPI 路由、CORS、健康检查，**一行不改就能用**
- `web-ui/chat_ui.html` — 改个标题就行

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
> 这套框架：LLM 自己理解用户的任何说法，自己判断该调哪个工具、要不要追问。
> 你的工作从「写规则」变成了「写 System Prompt + 写工具」。

---

## 🛠️ 8 个客房服务工具

| 工具函数 | 用途 | 对应 BRD 意图 |
|---|---|---|
| `request_supplies` | 客房物品补给（毛巾、矿泉水、牙刷等） | SVC_ROOM_001 |
| `request_cleaning` | 预约客房清洁打扫 | SVC_HK_001 |
| `report_maintenance` | 设备故障报修（空调、马桶、WiFi 等） | SVC_HK_001 |
| `request_laundry` | 洗衣/干洗/熨烫服务 | SVC_HK_001 |
| `call_hotel` | 呼叫前台/转接人工服务 | SVC_CALL_001 |
| `set_wake_up_call` | 设置叫醒/唤醒闹钟 | ALARM_001 |
| `delete_alarm` | 删除/取消闹钟（需二次确认） | ALARM_002 |
| `close_alarm` | 关闭正在响的闹钟（需二次确认） | ALARM_003 |

---

## 🚀 快速开始

### 前置条件

- Python 3.10+
- DeepSeek API Key（[获取地址](https://platform.deepseek.com/api_keys)）

### 安装 & 运行

```bash
# 1. 克隆项目
git clone https://github.com/your-username/hotel-agent-v2.git
cd hotel-agent-v2

# 2. 安装依赖
cd backend
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key

# 4. 启动 FastAPI 后端（生产模式）
python server.py
# 服务运行在 http://127.0.0.1:8000
# API 文档: http://127.0.0.1:8000/docs

# 5. 或者启动 Gradio 测试界面
python room_service_agent.py
# 界面运行在 http://127.0.0.1:7860
```

### 使用前端 UI

用浏览器打开 `web-ui/chat_ui.html`（需先启动后端）。

```bash
# Windows
start "" ..\web-ui\chat_ui.html

# macOS
open ../web-ui/chat_ui.html
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

// Response
{
  "response": "好的，两瓶矿泉水已经安排好了，客房服务员将在10分钟内送到301房间。",
  "session_id": "301"
}
```

### `GET /api/health` — 健康检查

```json
{
  "status": "ok",
  "agent": "RoomServiceAgent",
  "model": "deepseek-chat",
  "tools": ["request_supplies", "request_cleaning", ...]
}
```

### `DELETE /api/sessions/{session_id}` — 清除会话（退房）

---

## 📁 项目结构

```
hotel-agent-v2/
├── README.md                          ← 项目说明
├── .gitignore
├── .env.example
│
├── backend/                           ← 后端核心代码
│   ├── room_service_agent.py          ★ Agent 主程序（ReAct 循环）
│   ├── server.py                      ★ FastAPI 生产服务器
│   ├── requirements.txt               Python 依赖
│   ├── .env.example                   API Key 配置模板
│   ├── prompts/
│   │   └── system_prompt.txt          System Prompt（角色 + 工具指引）
│   ├── knowledge/
│   │   └── placeholder_info.txt       酒店知识库（RAG 检索源）
│   └── tools_api/
│       ├── __init__.py
│       └── mock_services.py           8 个工具函数（mock 实现）
│
├── web-ui/                            ← 前端
│   └── chat_ui.html                   纯 HTML 聊天界面
│
└── docs/                              ← 设计文档
    ├── BRD_客房服务Agent提取.md        需求说明书（BRD）
    ├── BRD全表.md                      需求全表
    ├── README_什么是真正的Agent.md       v1→v2 的理论讨论
    ├── README_重构方案_从流水线到Agent.md 重构设计方案
    └── README_重构执行清单.md            重构执行记录
```

---

## 🔧 技术栈

| 组件 | 技术 | 说明 |
|---|---|---|
| **编排框架** | LangGraph 1.2 | 有向图编排，条件路由，ReAct 循环 |
| **LLM** | DeepSeek Chat API | 兼容 OpenAI 格式，性价比高 |
| **记忆** | MemorySaver | 内存会话记忆，可按 session_id 隔离 |
| **RAG** | Chroma + all-MiniLM-L6-v2 | 轻量级向量检索，嵌入式运行 |
| **后端** | FastAPI + Uvicorn | 异步高性能，自动生成 OpenAPI 文档 |
| **前端** | HTML + Tailwind CSS + Vanilla JS | 零构建，浏览器直接打开 |
| **测试界面** | Gradio 6.x | 本地快速测试对话 |

---

## 🎯 对话示例

```
用户: 送两瓶矿泉水和一条毛巾到301
Agent: 🧠 决定调用 request_supplies(room="301", item="矿泉水", qty=2) + request_supplies(room="301", item="毛巾")
       好的，矿泉水两瓶和毛巾一条马上送到301，大约十分钟就到。

用户: 302的空调不制冷了，快来看看
Agent: 🧠 决定调用 report_maintenance(room="302", issue="空调不制冷", urgency="urgent")
       已经记录下来了，302房间的空调不制冷问题，维修师傅优先处理，马上到。

用户: 帮我预约明早7点的叫醒服务，房间503
Agent: 🧠 决定调用 set_wake_up_call(room="503", time="7:00")
       已为房间503设置唤醒服务，时间：明早7:00。届时电话将自动振铃。

用户: 帮我写一首诗
Agent: 🧠 非酒店话题 → 直接回复，不调工具
       抱歉先生/女士，我是您的酒店专属管家，仅为您解答酒店相关服务，写诗我帮不上忙呢。如果有其他需要，随时叫我。
```

---

## ⚠️ 注意事项

- **API Key 安全**：`.env` 文件已在 `.gitignore` 中排除。请使用 `.env.example` 作为模板创建自己的 `.env`，**切勿将真实 API Key 提交到代码仓库**。
- **Mock 工具**：当前工具函数返回模拟数据，生产环境需对接真实的酒店 PMS 系统。
- **HuggingFace 模型**：首次运行会自动下载 `all-MiniLM-L6-v2` 嵌入模型（~90MB），需联网。模型会被缓存到本地。
- **MemorySaver**：会话记忆存储在内存中，服务重启后清空。生产环境可升级为 `SqliteSaver` 做持久化。

---

## 📄 License

MIT License

---

*Built with LangGraph · DeepSeek · FastAPI · Gradio*

---

> ————

# 🏨 Hotel Room Service Agent v2

> **ReAct Agent Pattern** — LLM as the autonomous brain, 4-node LangGraph architecture
>
> Refactored from a v1 12-node pipeline, removing ~2,200 lines of rule code. The LLM goes from being a "tool" to being the "decision-maker".
>
> 🧩 **An industry-agnostic Agent skeleton** — swap the System Prompt and tool functions to turn it into an intelligent assistant for any domain.

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2-green)](https://langchain-ai.github.io/langgraph/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688)](https://fastapi.tiangolo.com/)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek%20Chat-536DFE)](https://platform.deepseek.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📌 v1 → v2 Evolution

| Dimension | v1 (Old Architecture) | v2 (New Architecture) |
|---|---|---|
| **Paradigm** | Frame-based Dialogue System | ReAct Agent (LLM-driven decisions) |
| **Graph Nodes** | 12 (7 are rule-code nodes) | **4** (Guard → RAG → Agent ⇄ Tools) |
| **Code Size** | ~3,000 lines | ~500 lines |
| **LLM's Role** | Just a JSON extractor | **The brain of the system** |
| **Intent Recognition** | Hard-coded mapping tables | LLM understands naturally |
| **Slot Validation** | Python rules (~510 lines) | LLM judges completeness itself |
| **Clarification** | Template-based | LLM generates natural follow-ups |
| **Tool Selection** | `INTENT_TOOL_MAP` lookup table | LLM autonomously picks the right tool |
| **Traceability** | Opaque rule chain | Every ReAct step is traceable |

### Architecture Comparison

```
v1: START → Guard → Locale → RAG → LLM(JSON) → SlotValidate → EntityResolve
           → CapabilityGate → RiskCheck → ToolExecute → ClarifyBuild
           → ResponseFormat → END
           (LLM is just one node in the chain)

v2: START → Guard → RAG → Agent(LLM + 8 Tools) ⇄ Tools → END
                          ↑___________________________|
                            ReAct autonomous loop
                            (LLM is the brain of the system)
```

### Core Philosophy Shift

> **v1's problem**: The code didn't trust the LLM, making every decision on its behalf. Every rule added was another blind spot.
>
> **v2's answer**: The LLM is the brain. The code only does two things — safety guardrails + providing tools. The LLM understands intent, judges whether it has enough information, decides to clarify or execute, picks the right tool, observes the result, and decides the next step — all by itself.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                    ReAct Agent                       │
│                                                     │
│  ┌──────────┐    ┌──────────┐    ┌───────────────┐  │
│  │  Guard   │───▶│   RAG    │───▶│  Agent (LLM)  │  │
│  │  Safety  │    │Knowledge │    │  + 8 Tools    │  │
│  └──────────┘    └──────────┘    └───────┬───────┘  │
│                                          │          │
│                           Text reply ◄───┼──► Tool call│
│                                          │          │
│                                 ┌────────▼───────┐  │
│                                 │  Tool Executor  │  │
│                                 │  (8 mock tools) │  │
│                                 └────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 4 Graph Nodes

| Node | Responsibility | Who Decides |
|---|---|---|
| **Guard** | Filters sensitive content (politics/violence/NSFW), rejects if hit | Code (safety baseline) |
| **RAG** | Retrieves relevant knowledge from the hotel KB, injects into System Prompt | Code (knowledge augmentation) |
| **Agent** | Understands intent, judges info completeness, decides clarify/execute, picks tools, generates replies | **LLM autonomously** |
| **Tools** | Executes 8 room service tool functions, returns results to Agent | Code (execution layer) |

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
│  │  LangGraph orchestration → Guard→RAG│    │
│  │                      → Agent⇄Tools   │    │
│  │  ReAct loop           → Auto-decide  │    │
│  │  FastAPI server       → Production API│   │
│  │  Multi-session memory → Per-user iso  │    │
│  │  Content safety       → Keyword filter│    │
│  │  Web UI               → Chat interface│    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

### 3 Steps to Build a New Agent

| Step | What to Change | Effort | Example (→ Customer Service Agent) |
|---|---|---|---|
| **① Persona** | `prompts/system_prompt.txt` | 5 min | "You are an e-commerce support specialist handling returns and shipping inquiries…" |
| **② Tools** | `tools_api/mock_services.py` | 30 min | `query_order()` `process_refund()` `check_logistics()` |
| **③ Knowledge** | `knowledge/placeholder_info.txt` | 5 min | Return policies, shipping rates, after-sales procedures |

### What You Don't Touch

- `room_service_agent.py` — Graph orchestration, ReAct loop, LLM invocation — **zero changes needed**
- `server.py` — FastAPI routes, CORS, health checks — **works out of the box**
- `web-ui/chat_ui.html` — just change the title

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
> This framework: the LLM understands any phrasing a user might throw at it, decides which tool to call, and whether to ask for clarification — all by itself.
> Your job shifts from "writing rules" to "writing System Prompts + writing tools".

---

## 🛠️ 8 Room Service Tools

| Tool Function | Purpose | BRD Intent |
|---|---|---|
| `request_supplies` | Deliver amenities (towels, water, toothbrushes, etc.) | SVC_ROOM_001 |
| `request_cleaning` | Schedule housekeeping | SVC_HK_001 |
| `report_maintenance` | Report equipment issues (AC, toilet, WiFi, etc.) | SVC_HK_001 |
| `request_laundry` | Laundry / dry cleaning / ironing | SVC_HK_001 |
| `call_hotel` | Transfer to front desk / human staff | SVC_CALL_001 |
| `set_wake_up_call` | Set wake-up / morning call alarm | ALARM_001 |
| `delete_alarm` | Delete/cancel alarm (requires confirmation) | ALARM_002 |
| `close_alarm` | Dismiss a ringing alarm (requires confirmation) | ALARM_003 |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- DeepSeek API Key ([Get one here](https://platform.deepseek.com/api_keys))
- *(Optional — to use OpenAI instead, just change `base_url` and `model` in `room_service_agent.py`)*

### Install & Run

```bash
# 1. Clone the repo
git clone https://github.com/your-username/hotel-agent-v2.git
cd hotel-agent-v2

# 2. Install dependencies
cd backend
pip install -r requirements.txt

# 3. Configure API Key
cp .env.example .env
# Edit .env and paste your DeepSeek API Key

# 4. Start FastAPI backend (production mode)
python server.py
# Server runs at http://127.0.0.1:8000
# API docs: http://127.0.0.1:8000/docs

# 5. Or launch Gradio test UI
python room_service_agent.py
# UI runs at http://127.0.0.1:7860
```

### Using the Web UI

Open `web-ui/chat_ui.html` in your browser (backend must be running first).

```bash
# Windows
start "" ..\web-ui\chat_ui.html

# macOS
open ../web-ui/chat_ui.html

# Linux
xdg-open ../web-ui/chat_ui.html
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

// Response
{
  "response": "Sure, two bottles of water will be delivered to room 301 within 10 minutes.",
  "session_id": "301"
}
```

### `GET /api/health` — Health Check

```json
{
  "status": "ok",
  "agent": "RoomServiceAgent",
  "model": "deepseek-chat",
  "tools": ["request_supplies", "request_cleaning", ...]
}
```

### `DELETE /api/sessions/{session_id}` — Clear Session (check-out)

---

## 📁 Project Structure

```
hotel-agent-v2/
├── README.md                          ← You are here (CN + EN)
├── .gitignore
├── .env.example
│
├── backend/                           ← Core backend
│   ├── room_service_agent.py          ★ Agent main program (ReAct loop)
│   ├── server.py                      ★ FastAPI production server
│   ├── requirements.txt               Python dependencies
│   ├── .env.example                   API key config template
│   ├── prompts/
│   │   └── system_prompt.txt          System Prompt (role + tool guidance)
│   ├── knowledge/
│   │   └── placeholder_info.txt       Hotel knowledge base (RAG source)
│   └── tools_api/
│       ├── __init__.py
│       └── mock_services.py           8 tool functions (mock implementation)
│
├── web-ui/                            ← Frontend
│   └── chat_ui.html                   Zero-build HTML chat interface
│
└── docs/                              ← Design documents (Chinese)
    ├── BRD_requirements.md             BRD extracted for room service
    ├── BRD_full_table.md               Full BRD table
    ├── what-is-an-agent.md            v1→v2 theoretical discussion
    ├── refactor-plan.md               Refactoring design plan
    └── refactor-checklist.md          Refactoring execution log
```

---

## 🔧 Tech Stack

| Component | Technology | Notes |
|---|---|---|
| **Orchestration** | LangGraph 1.2 | Directed graph, conditional routing, ReAct loop |
| **LLM** | DeepSeek Chat API | OpenAI-compatible format, cost-effective |
| **Memory** | MemorySaver | In-memory sessions, isolated by session_id |
| **RAG** | Chroma + all-MiniLM-L6-v2 | Lightweight vector search, embedded mode |
| **Backend** | FastAPI + Uvicorn | Async, auto-generated OpenAPI docs |
| **Frontend** | HTML + Tailwind CSS + Vanilla JS | Zero build, open in browser |
| **Test UI** | Gradio 6.x | Quick local chat testing |

---

## 🎯 Conversation Examples

```
Guest: Send two bottles of water and a towel to 301
Agent: 🧠 Decides to call request_supplies(room="301", item="water", qty=2)
          + request_supplies(room="301", item="towel")
       Sure, two bottles of water and a towel will be delivered to room 301
       right away, about 10 minutes.

Guest: The AC in 302 isn't cooling, come fix it now!
Agent: 🧠 Decides to call report_maintenance(room="302", issue="AC not cooling", urgency="urgent")
       I've logged this — room 302 AC issue. A technician will be dispatched
       immediately as a priority.

Guest: Set a wake-up call for 7am tomorrow, room 503
Agent: 🧠 Decides to call set_wake_up_call(room="503", time="7:00")
       Wake-up call set for room 503 at 7:00 AM tomorrow.
       The phone will ring automatically at that time.

Guest: Write me a poem
Agent: 🧠 Out of scope → replies directly, no tool call
       I'm sorry, I'm your hotel service assistant and can only help with
       hotel-related requests. Is there anything else I can assist you with?
```

---

## ⚠️ Important Notes

- **API Key Security**: `.env` is excluded via `.gitignore`. Use `.env.example` as a template — **never commit your real API key**.
- **Mock Tools**: Tool functions currently return simulated data. For production, connect to your real business systems (PMS, CRM, etc.).
- **HuggingFace Model**: The `all-MiniLM-L6-v2` embedding model (~90MB) is downloaded automatically on first run. It's cached locally afterwards.
- **LLM Provider**: Defaults to DeepSeek. To use OpenAI, change `base_url` to `https://api.openai.com/v1` and `model` to `gpt-4o` in `room_service_agent.py` — everything else stays the same.
- **MemorySaver**: Conversations are stored in memory and cleared on restart. Upgrade to `SqliteSaver` for persistent storage in production.

---

## 📄 License

MIT License

---

*Built with LangGraph · DeepSeek · FastAPI · Gradio*
