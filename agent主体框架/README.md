# agent主体框架/ — 客房服务 Agent 核心代码

---

## ⚡ 5 分钟快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key（重要！）
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key
# 获取 Key: https://platform.deepseek.com/api_keys

# 3. 启动
python room_service_agent.py        # Gradio 调试界面
python server.py                    # FastAPI HTTP 服务
python main_router.py               # 总控路由
```

---

## 一、这个项目是干什么的？

**客房服务 Agent** 是五星级酒店多智能体系统中的一个子 Agent。客人在房间里说话 → 语音 Agent 转成文字 → 控制 Agent 判断该分给谁 → 如果涉及客房服务就发给你 → 你理解客人需求、校验合法性、调用工具执行、返回结构化结果。

这个文件夹包含了客房服务 Agent 的全部核心代码。

---

## 二、整体架构

| 层 | 文件夹 | 一句话 |
|----|--------|--------|
| 配置层 | `config/` | BRD 规则数字化——改规则只改 JSON，不改代码 |
| 模型层 | `models/` | 统一数据契约——所有节点读写同一种格式 |
| 提示词层 | `prompts/` | txt 管"怎么说"，py 管"知道什么" |
| 逻辑层 | `core/` | 12 个节点 SOP 流水线——每个节点只做一件事 |
| 执行层 | `tools_api/` | 8 个工具函数——Agent 的"手" |
| 知识层 | `knowledge/` | 酒店静态信息——RAG 检索 |
| 测试层 | `tests/` | AC1~AC5 验收测试 |
| 入口 | `room_service_agent.py` | LangGraph 图编排——12 节点串联 |
| 路由 | `main_router.py` | 总控路由——LLM 意图分类 → 5 路 Agent 分发 |
| 服务 | `server.py` | FastAPI HTTP 接口——返回结构化 JSON |

---

## 三、12 节点完整流水线

```
客人消息: "送两瓶矿泉水到301"
    │
    ▼ ① guardrail          ← 安全护栏（关键词拦截）
    │
    ▼ ② locale_resolver    ← 语言检测（zh-CN/en-US/zh-GD/en-SG）
    │
    ▼ ③ rag_retrieve       ← RAG 知识库检索
    │
    ▼ ④ chatbot            ← JSON 模式 LLM → {intents, slots, entities}
    │
    ▼ ⑤ slot_validator     ← enum/range/required/default 校验
    │
    ▼ ⑥ entity_resolver    ← 房间号提取 + 歧义检测
    │
    ▼ ⑦ capability_gate    ← 能力矩阵 Gating（service/alarm）
    │
    ▼ ⑧ risk_checker       ← 风控红线 + 二次确认
    │
    ▼ tool_executor         ← 手动工具路由 → request_supplies(301, 矿泉水)
    │
    ▼ ⑩ response_formatter ← FinalOutput {result_type, intent, slots, trace}
    │
    ▼ END

旁路: 任何节点失败 → ⑨ clarify_builder → ⑩ response_formatter → END
```

---

## 四、目录树

```
agent主体框架/
├── config/                          ← BRD 规则 JSON 化（6 个文件）
│   ├── general.json                 ← 通用枚举（语言/设备/位置/范围）
│   ├── intent_definitions.json      ← 6 条客房服务意图定义
│   ├── slot_definitions.json        ← 11 个槽位校验规则
│   ├── capability_matrix.json       ← 能力矩阵（service + alarm）
│   └── risk_control.json            ← 风控红线（4 intent + 10 GR）
│
├── models/
│   └── models.py                    ← 3 枚举 + 5 数据类 + 辅助函数
│
├── prompts/
│   ├── system_prompt.txt            ← 静态模板（角色 + 意图判定规则）
│   └── prompt_loader.py             ← 动态加载器（从 JSON 拼 prompt）
│
├── core/                            ← 12 节点 SOP 流水线
│   ├── locale_resolver.py           ← ② 语言检测
│   ├── slot_validator.py            ← ⑤ 槽位校验
│   ├── entity_resolver.py           ← ⑥ 实体解析
│   ├── capability_gate.py           ← ⑦ 能力门控
│   ├── risk_checker.py              ← ⑧ 风控红线
│   ├── clarify_builder.py           ← ⑨ 澄清追问
│   └── response_formatter.py        ← ⑩ 最终输出
│
├── tools_api/
│   └── mock_services.py             ← 8 个工具（5 服务类 + 3 闹钟类）
│
├── knowledge/
│   └── placeholder_info.txt         ← 酒店知识库
│
├── tests/
│   └── test_room_service.py         ← AC1~AC5 验收测试（18 个用例）
│
├── room_service_agent.py            ← ★ LangGraph 图编排（12 节点）
├── main_router.py                   ← ★ 总控路由（LLM 分类 → 5 路分发）
├── server.py                        ← ★ FastAPI HTTP 服务
└── requirements.txt
```

---

## 五、当前状态（Day 10）

| 组件 | 状态 |
|------|------|
| 配置层（5 个 JSON） | ✅ 完成 |
| 数据模型（models.py） | ✅ 完成 |
| 提示词（txt + loader） | ✅ 完成 |
| 流水线（12 节点） | ✅ 完成 |
| 工具函数（8 个） | ✅ 完成 |
| 验收测试（18 用例） | ✅ 全部通过 |
| HTTP 服务（结构化 JSON） | ✅ 完成 |
| 总控路由 | ✅ 完成 |

**BRD 对齐度：从 Day 0 的 ~30% → Day 10 的 ~95%。**

---

## 六、启动方式

```bash
# 交互测试（Gradio 界面）
python room_service_agent.py

# HTTP 服务
python server.py
# 或: uvicorn server:app --host 0.0.0.0 --port 8000

# 总控路由（5 路分发）
python main_router.py

# 验收测试
python tests/test_room_service.py
```

## 七、API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 核心对话（返回 result_type + intent + decision_trace） |
| GET | `/api/health` | 健康检查 |
| GET | `/api/sessions` | 活跃会话列表 |
| DELETE | `/api/sessions/{id}` | 清除会话（退房） |
