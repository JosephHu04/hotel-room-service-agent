# 酒店客房服务 Agent

> ReAct 模式智能体 — LLM 自主决策，4 节点 LangGraph 架构

## 项目结构

```
hotel agent/
├── README.md                        ← 你在这里
├── README_什么是真正的Agent.md        ← 理论讨论：流水线 vs Agent
├── README_重构方案_从流水线到Agent.md  ← 设计方案：12 节点 → 4 节点
├── README_重构执行清单.md             ← 执行记录：已完成的步骤
│
├── agent主体框架/                    ← 核心代码
│   ├── room_service_agent.py        ← ★ Agent 主程序（ReAct 循环）
│   ├── server.py                    ← FastAPI 生产服务器
│   ├── main_router.py               ← 总控路由（5 路分发）
│   ├── prompts/
│   │   └── system_prompt.txt        ← System Prompt（~60 行）
│   ├── tools_api/
│   │   └── mock_services.py         ← 8 个工具函数
│   ├── knowledge/
│   │   └── placeholder_info.txt     ← 酒店知识库（RAG 用）
│   ├── requirements.txt             ← Python 依赖
│   └── .env                         ← DeepSeek API Key
│
├── demand/                          ← 需求文档
│   ├── BRD_客房服务Agent提取.md
│   ├── BRD_客房服务Agent_规划与差距分析.md
│   ├── BRD全表.md
│   └── outline/
│       ├── outline.tex
│       └── outline.pdf
│
└── ui界面文件/                       ← 前端
    └── chat_ui.html                 ← 聊天界面
```

## 快速启动

```bash
cd agent主体框架

# 安装依赖
pip install -r requirements.txt

# 启动 Gradio 测试界面
python room_service_agent.py

# 或启动 FastAPI 服务器
python server.py
```

## 架构

```
START → guardrail（安全护栏）→ RAG（知识检索）→ agent（LLM + 8工具）⇄ tools → END
                                                      ↑_____________|
                                                       ReAct 自主循环
```

- **LLM**：DeepSeek API（deepseek-chat）
- **工具**：物品补给、清洁打扫、报修维护、洗衣服务、呼叫前台、叫醒闹钟
- **图节点**：4 个（从旧架构的 12 个精简而来）
- **路由**：main_router 5 路分发（客房/前台/餐厅/礼宾/总机）

## 8 个工具

| 工具 | 用途 |
|------|------|
| `request_supplies` | 送毛巾、矿泉水、牙刷等 |
| `request_cleaning` | 安排打扫房间 |
| `report_maintenance` | 报修（空调、马桶、WiFi 等） |
| `request_laundry` | 洗衣/干洗/熨烫 |
| `call_hotel` | 呼叫前台/转接人工 |
| `set_wake_up_call` | 设置叫醒闹钟 |
| `delete_alarm` | 删除闹钟 |
| `close_alarm` | 关闭正在响的闹钟 |
