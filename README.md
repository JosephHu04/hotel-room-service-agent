# 🏨 酒店客房服务 Agent — Hotel Room Service AI Agent

<p align="center">
  <strong>基于 LangGraph + DeepSeek 的智能客房服务对话系统</strong><br>
  Building an AI-powered Hotel Room Service Agent with LLM + Multi-Node Pipeline
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/LangGraph-0.2+-green.svg" alt="LangGraph">
  <img src="https://img.shields.io/badge/LLM-DeepSeek%20Chat-purple.svg" alt="DeepSeek">
  <img src="https://img.shields.io/badge/Framework-FastAPI-orange.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/Status-Production%20Ready-brightgreen.svg" alt="Status">
</p>

---

## 📖 项目简介 | Overview

一个面向酒店的 **AI 客房服务 Agent**，客人通过自然语言提出需求（送物品、打扫、报修、洗衣、叫醒、呼叫前台），Agent 自动理解意图、校验参数、风控确认、执行操作，并返回结构化结果。

**核心能力**：理解中文口语 → 识别 6 种客房意图 → 12 节点流水线校验 → 调用 8 个工具函数 → 返回结构化 JSON

### ✨ 亮点 | Highlights

- 🧠 **LLM 驱动的意图理解**：DeepSeek Chat 模型，强制 JSON 结构化输出
- 🔒 **12 节点安全流水线**：护栏 → 语言检测 → RAG → LLM → 槽位校验 → 实体解析 → 能力门控 → 风控确认 → 工具执行 → 澄清构建 → 格式化输出
- 📋 **BRD 完整对齐**：所有规则数字化为 JSON 配置文件，与酒店 BRD 需求文档一一对应
- 🔧 **8 个工具函数**：补给配送、清洁打扫、报修维护、洗衣服务、叫醒设置、闹钟管理、前台呼叫
- 🧪 **18 个验收用例**：覆盖 AC1-AC5 全部验收标准
- 🌐 **FastAPI 生产接口**：标准 RESTful API，支持多会话、结构化 JSON 响应

### 🎯 适用场景 | Use Cases

| 场景 | 客人说什么 | Agent 做什么 |
|------|-----------|-------------|
| 🧴 物品补给 | "送两瓶矿泉水到301" | 识别 ROOM_SERVICE → 校验 → 确认 → 调用 `request_supplies` |
| 🧹 客房清洁 | "打扫一下302" | 识别 HOUSEKEEPING → 解析时间 → 安排保洁 |
| 🔧 设备报修 | "空调不制冷了" | 识别 HOUSEKEEPING → 生成工单 → `report_maintenance` |
| 👔 洗衣服务 | "西装需要干洗，405房" | 识别 HOUSEKEEPING → `request_laundry` |
| ⏰ 叫醒服务 | "明早7点叫醒我，503" | 识别 ALARM → 解析时间 → `set_wake_up_call` |
| 📞 呼叫前台 | "帮我叫前台过来" | 识别 HOTEL_CALL → 确认 → `call_hotel` |

---

## 🏗️ 架构设计 | Architecture

### 12 节点流水线

```
客人消息: "送两瓶矿泉水到301"
    │
    ▼ ┌─────────────────────────────────────────┐
  ①  │ guardrail         安全护栏（关键词拦截）    │
      └─────────────────────────────────────────┘
    │ SAFE                              │ UNSAFE → 拒绝
    ▼
  ②  locale_resolver    语言检测（zh-CN/en-US/zh-GD/en-SG）
    │
    ▼
  ③  rag_retrieve       RAG 知识库检索（酒店设施/服务信息）
    │
    ▼
  ④  chatbot            ★ JSON 模式 LLM → {intents, slots, entities}
    │                    使用 DeepSeek Chat，强制结构化输出
    ▼
  ⑤  slot_validator     槽位校验（enum/range/required/default）
    │                    11 个槽位的合法性检查
    ▼
  ⑥  entity_resolver    实体解析（房间号提取 + 歧义检测）
    │
    ▼
  ⑦  capability_gate    能力门控（service/alarm 设备能力矩阵）
    │
    ▼
  ⑧  risk_checker       风控红线（高风险操作二次确认 + GR-01~10）
    │
    ▼
      tool_executor      手动工具路由 → request_supplies(301, 矿泉水)
    │
    ▼
  ⑩  response_formatter FinalOutput {result_type, intent, slots, trace}
    │
    ▼
   END → 返回给客人: "好的先生，两瓶矿泉水马上送到301，大约10分钟"
```

> 💡 **为什么是 12 个节点？** 每个节点只做一件事，职责单一，便于测试、调试和规则热更新。详见 [agent主体框架/core/README.md](agent主体框架/core/README.md)。

### 数据流

| 层 | 目录 | 职责 |
|----|------|------|
| 📋 配置层 | `config/` | BRD 规则 JSON 化 — 改规则只改 JSON，不改代码 |
| 📐 模型层 | `models/` | 统一数据契约 — 3 枚举 + 5 数据类 |
| 📝 提示词层 | `prompts/` | System Prompt — 静态模板 + 动态加载器 |
| ⚙️ 逻辑层 | `core/` | 10 个 SOP 节点 — 每个节点只做一件事 |
| 🔧 执行层 | `tools_api/` | 8 个工具函数 — Agent 的"手" |
| 📚 知识层 | `knowledge/` | 酒店静态信息 — RAG 向量检索 |

---

## 📁 项目结构 | Project Structure

```
hotel-agent/
├── .gitignore                         # Git 忽略规则
├── README.md                          # 项目总览（你在看这个）
│
├── agent主体框架/                      # ★ 核心代码（33 个文件）
│   ├── room_service_agent.py          # LangGraph 图编排 — 12 节点流水线
│   ├── main_router.py                 # 总控路由 — LLM 分类 → 5 路分发
│   ├── server.py                      # FastAPI HTTP 服务
│   ├── requirements.txt               # Python 依赖清单
│   ├── .env.example                   # 环境变量模板
│   │
│   ├── config/                        # BRD 规则 JSON（6 个配置文件）
│   │   ├── general.json               # 通用枚举：语言/设备/位置/范围
│   │   ├── intent_definitions.json    # 6 条客房服务意图定义
│   │   ├── slot_definitions.json      # 11 个槽位校验规则
│   │   ├── capability_matrix.json     # 能力矩阵（service + alarm）
│   │   ├── risk_control.json          # 风控红线（10 条全局红线）
│   │   ├── lexicon.json               # 实体词表
│   │   └── README.md                  # 配置文件详细说明
│   │
│   ├── core/                          # 流水线节点（10 个节点）
│   │   ├── locale_resolver.py         # ② 语言检测（4 种语言）
│   │   ├── slot_validator.py          # ⑤ 槽位校验（4 种校验类型）
│   │   ├── entity_resolver.py         # ⑥ 实体解析（房间号 + 歧义）
│   │   ├── capability_gate.py         # ⑦ 能力门控
│   │   ├── risk_checker.py            # ⑧ 风控确认 + 二次确认
│   │   ├── clarify_builder.py         # ⑨ 澄清追问（14 个原因码）
│   │   ├── response_formatter.py      # ⑩ 最终输出格式化
│   │   └── README.md                  # 节点详细说明
│   │
│   ├── tools_api/mock_services.py     # 8 个工具函数
│   ├── prompts/                       # System Prompt
│   ├── knowledge/                     # RAG 知识库
│   ├── models/models.py               # 数据模型
│   └── tests/test_room_service.py     # 18 个验收用例
│
├── ui界面文件/chat_ui.html            # 前端聊天界面
└── demand/                            # BRD 需求文档
```

---

## 🚀 快速开始 | Quick Start

### 前置要求

- **Python** >= 3.10
- **DeepSeek API Key** → [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) 免费注册获取
- （可选）Ollama 本地模型

### 1. 克隆项目

```bash
git clone https://github.com/YOUR_USERNAME/hotel-agent.git
cd hotel-agent
```

### 2. 安装依赖

```bash
pip install -r agent主体框架/requirements.txt
```

### 3. 配置 API Key

```bash
# 复制环境变量模板
cp agent主体框架/.env.example agent主体框架/.env

# 编辑 .env 文件，填入你的 DeepSeek API Key
# 内容如下：
```

```env
# DeepSeek API（必需，免费注册即送额度）
DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 服务器配置（可选）
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

### 4. 启动

```bash
# 方式一：Gradio 本地调试界面（最简单）
python agent主体框架/room_service_agent.py

# 方式二：FastAPI HTTP 服务（生产环境）
python agent主体框架/server.py
# 然后访问 http://localhost:8000/docs 查看 Swagger API 文档

# 方式三：总控路由（多 Agent 分发）
python agent主体框架/main_router.py
```

### 5. 测试

```bash
python agent主体框架/tests/test_room_service.py
```

---

## 📡 API 文档 | API Reference

### 接口列表

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat` | 核心对话接口 |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/sessions` | 活跃会话列表 |
| `DELETE` | `/api/sessions/{id}` | 清除会话（退房后调用） |

### POST /api/chat — 对话接口

**请求**：
```json
{
  "message": "送两瓶矿泉水到301",
  "session_id": "301"
}
```

**响应**：
```json
{
  "response": "好的先生，两瓶矿泉水马上送到301房间，大约10分钟为您送达。",
  "session_id": "301",
  "result_type": "execute",
  "final_intent": {
    "L1": "ROOM_SERVICE",
    "L2": "CREATE_REQUEST",
    "L3": "DEFAULT",
    "id": "SVC_ROOM_001",
    "score": 0.95
  },
  "decision_trace": [
    {"step": "guardrail", "result": "pass"},
    {"step": "locale_resolver", "result": "pass", "locale": "zh-CN"},
    {"step": "chatbot", "result": "pass", "intent": "ROOM_SERVICE"},
    {"step": "slot_validator", "result": "pass", "slots_validated": 4},
    {"step": "entity_resolver", "result": "pass", "room": "301"},
    {"step": "capability_gate", "result": "pass"},
    {"step": "risk_checker", "result": "pass"},
    {"step": "tool_executor", "tool_name": "request_supplies"}
  ],
  "tool_calls": ["request_supplies"]
}
```

**三种 result_type**：

| 类型 | 含义 | 示例场景 |
|------|------|---------|
| `execute` | 校验通过，已执行 | "送两瓶水到301" → 成功配送 |
| `need_clarify` | 需要追问/确认 | "打扫一下"（缺房间号）→ 追问 |
| `reject` | 拒绝 | 政治/暴力等敏感内容 → 礼貌拒绝 |

---

## 🛠️ 技术栈 | Tech Stack

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 🧠 大模型 | DeepSeek Chat API | OpenAI 兼容接口，中文能力强，价格低廉 |
| 🔗 对话编排 | LangGraph 0.2+ | 有向图状态机，支持条件路由和持久记忆 |
| 🔍 向量检索 | Chroma + all-MiniLM-L6-v2 | 轻量级本地向量库，无需外部服务 |
| 🌐 HTTP 框架 | FastAPI + Uvicorn | 高性能异步框架，自动生成 Swagger 文档 |
| 🖥️ 调试界面 | Gradio 4.0+ | 一键启动 Web 聊天界面 |
| 📋 数据校验 | Pydantic | 请求/响应模型自动校验 |
| 💾 会话记忆 | LangGraph MemorySaver | 内存存储，支持按 session_id 隔离 |

---

## 📚 学习指南 | Learning Guide

如果你是第一次接触这个项目，建议按以下顺序阅读：

| 顺序 | 阅读内容 | 预计时间 | 收获 |
|------|---------|---------|------|
| 1 | 本页面 | 5 min | 了解项目全貌和启动方式 |
| 2 | [agent主体框架/README.md](agent主体框架/README.md) | 10 min | 理解 12 节点流水线架构 |
| 3 | [config/README.md](agent主体框架/config/README.md) | 15 min | 学会"配置即规则"的设计思路 |
| 4 | [models/README.md](agent主体框架/models/README.md) | 10 min | 看懂统一数据契约 |
| 5 | [core/README.md](agent主体框架/core/README.md) | 20 min | 逐个理解 10 个流水线节点 |
| 6 | [tools_api/README.md](agent主体框架/tools_api/README.md) | 10 min | 了解 8 个工具函数设计 |
| 7 | [demand/BRD全表.md](demand/BRD全表.md) | 15 min | 对照需求文档验证完整性 |

---

## 🔧 开发指南 | Development

### 如何新增一个服务类型

1. 在 `config/intent_definitions.json` 添加意图定义
2. 在 `config/slot_definitions.json` 添加槽位规则
3. 在 `tools_api/mock_services.py` 添加工具函数
4. 在 `room_service_agent.py` 添加意图→工具映射

### 如何替换为真实酒店系统

当前工具函数为 Mock 实现，接入真实 PMS（Property Management System）只需：

1. 修改 `tools_api/mock_services.py` 中的函数实现
2. 将返回的 `message` 替换为真实 API 调用结果
3. 保持函数签名和返回格式不变，上层代码无需修改

### 如何切换为大模型

默认使用 DeepSeek Chat。如需切换为其他模型：

```python
# 修改 room_service_agent.py 中的 llm_json 和 llm_chat
llm_json = ChatOpenAI(
    model="你的模型名",       # 如 gpt-4o, qwen-plus, glm-4
    api_key="你的API Key",
    base_url="你的Base URL", # OpenAI / 阿里云 / 智谱 等
)
```

---

## ❓ 常见问题 | FAQ

<details>
<summary><strong>Q: 为什么用 12 个节点而不是让 LLM 直接调用工具？</strong></summary>

这是传统流水线架构（Frame-based Dialogue System）的做法——每个节点职责单一，可独立测试和调试。这种做法在确定性要求高的酒店场景有其合理性（如风控红线不可绕过），但也有过度工程的代价。相关讨论见 core/README.md。
</details>

<details>
<summary><strong>Q: DeepSeek API 免费吗？</strong></summary>

DeepSeek 新用户注册赠送免费额度。即使付费，价格也远低于 GPT-4（约 1/10），非常适合学习和原型开发。
</details>

<details>
<summary><strong>Q: 能在没有网络的环境运行吗？</strong></summary>

可以使用 Ollama 本地模型替代 DeepSeek API。修改 `room_service_agent.py` 中的 LLM 配置为 `ChatOllama`，并在 `requirements.txt` 中启用 `langchain-ollama`。
</details>

<details>
<summary><strong>Q: 支持多语言吗？</strong></summary>

支持普通话（zh-CN）、粤语（zh-GD）、美式英语（en-US）、新加坡英语（en-SG）四种语言，由 `locale_resolver` 节点自动检测。
</details>

---

## 🤝 贡献 | Contributing

欢迎提交 Issue 和 Pull Request！

- 🐛 发现 Bug → 提交 Issue，附上复现步骤
- 💡 功能建议 → 提交 Issue，描述使用场景
- 🔧 代码贡献 → Fork → 新分支 → PR

---

## 📄 许可证 | License

MIT License — 详见 [LICENSE](LICENSE) 文件（如有）。

---

## 🔗 相关链接 | Links

- [DeepSeek 开放平台](https://platform.deepseek.com) — 获取 API Key
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/) — 对话图编排框架
- [FastAPI 文档](https://fastapi.tiangolo.com/) — HTTP 框架
- [Gradio 文档](https://www.gradio.app/) — 交互界面框架

---

<p align="center">
  <sub>Built with ❤️ for the hospitality industry | 为酒店行业而建</sub>
</p>
