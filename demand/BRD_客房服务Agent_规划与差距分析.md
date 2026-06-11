# 客房服务 Agent — BRD 对齐规划 & 差距分析

> **基线文档**：[BRD_客房服务Agent提取.md](BRD_客房服务Agent提取.md)  
> **分析日期**：2026-06-09  
> **当前代码**：`llm/room_service_agent.py` + `llm/tools_api/mock_services.py` + `llm/main_router.py`

---

## 一、目标架构全景（BRD 要求 vs 现状）

```
                    ┌───────── 语音 Agent ───────┐
                    │  用户文本 (user_text)        │
                    └──────────┬─────────────────┘
                               ▼
     ┌─────────────────────────────────────────────────┐
     │              你的 客房服务 Agent                 │
     │                                                 │
     │  ┌──────────────────────────────────────────┐   │
     │  │ Phase 1: 意图识别 → Intent L1/L2/L3 + ID  │    │
     │  │ Phase 2: 槽位提取 → raw slots             │    │
     │  │ Phase 3: 实体解析 → canonical entities    │   │
     │  │ Phase 4: 能力 Gating → pass/block        │    
     │  │ Phase 5: 槽位校验 → valid/clamp/default   │   │
     │  │ Phase 6: 风控红线 → safe/risky            │   │
     │  │ Phase 7: NeedClarify → 澄清 struct        │   │
     │  │ Phase 8: 输出决策 → execute/clarify/reject│   │
     │  └──────────────────────────────────────────┘   │
     │                      │                          │
     │           ┌──────────┼──────────┐               │
     │           ▼          ▼          ▼               │
     │       execute   need_clarify   reject           │
     │       →工具调用  →澄清追问     →礼貌拒绝          │
     └─────────────────────────────────────────────────┘
```

---

## 二、分阶段搭建流程 + 差距分析

### 图例说明

| 标记 | 含义 |
|------|------|
| ✅ | 已实现且符合 BRD |
| ⚠️ | 已有但需调整增强 |
| ❌ | 完全缺失，需要新建 |
| 🔴 | 与 BRD 冲突，需要删改 |

---

## Phase 0：基础设施 & 配置表落地

### 0.1 配置表 JSON 化

**BRD 要求**：§8 配置表是 SSOT（Single Source of Truth），所有校验必须基于配置表。

**现状**：❌ 配置表仅存在于 Markdown 文档中，代码里没有任何加载。

**差距**：

| 项目 | BRD 来源 | 当前状态 | 行动 |
|------|----------|----------|------|
| General 枚举表 | §8.1 | ❌ 不存在 | 新建 `config/general.json` |
| IntentDefinitions | §8.2 | ❌ 不存在 | 新建 `config/intent_definitions.json`（仅6条） |
| SlotDefinitions | §8.3 | ❌ 不存在 | 新建 `config/slot_definitions.json`（仅11条） |
| CapabilityMatrix | §8.4 | ❌ 不存在 | 新建 `config/capability_matrix.json` |
| language 表 | §8.1 | ❌ 不存在 | 含在 general.json |

**行动项**：

```
llm/
├── config/
│   ├── general.json              ← 新建：language/device_type/location/scope 枚举
│   ├── intent_definitions.json   ← 新建：6条客房服务 intent（SVC_ROOM_001等）
│   ├── slot_definitions.json     ← 新建：11个客房服务槽位定义（SL_001等）
│   ├── capability_matrix.json    ← 新建：service 设备能力矩阵
│   └── risk_control.json         ← 新建：intent级风险等级 + 全局红线 GR-01~10
```

**优先级**：🔴 **最高 — 所有后续 Phase 都依赖配置表**


## Phase 1：意图识别（Intent Classification）

### BRD 要求（§9 步骤 1-3-5）

```
输入: user_text, locale, device_context
输出: final_intent = {L1, L2, L3, ID} + 候选意图列表
```

你的 4 个 intent（从 IntentDefinitions）：

| ID | L1 | L2 | L3 |
|---|---|---|---|
| SVC_ROOM_001 | ROOM_SERVICE | CREATE_REQUEST | DEFAULT |
| SVC_HK_001 | HOUSEKEEPING | CREATE_REQUEST | DEFAULT |
| SVC_CALL_001 | HOTEL_CALL | CREATE_REQUEST | DEFAULT |
| ALARM_001 | ALARM | SETTINGS | DEFAULT |
| ALARM_002 | ALARM | DELETE | DEFAULT |
| ALARM_003 | ALARM | CLOSE | DEFAULT |

### 现状 vs 需求

| BRD 要求 | 当前代码 | 差距 |
|----------|----------|------|
| 输出结构化 intent L1/L2/L3 + ID | ❌ LLM 只输出自然语言，靠 main_router 做简单分类 | 需要 system prompt 注入 intent 定义 + 要求 JSON 输出 |
| locale 检测与回退 | ❌ 完全没有 | 需要加 locale 检测节点 |
| device_context 处理 | ❌ 没有接收 device_context | 需要加输入参数 |
| 候选意图管理 | ❌ 单一 intent 决策 | 需要输出 candidates 列表 |
| 与 main_router 协作 | ⚠️ main_router 先分流 5 个 agent，再进 room_service | 架构 OK，但需要 room_service 内部再做细粒度 intent 分类 |

### 行动项

| # | 行动 | 涉及文件 | 类型 |
|---|------|----------|------|
| 1.1 | 重写 system_prompt，注入 6 条 intent 定义 + required/optional 槽位 | `prompts/system_prompt.txt` | 🔴 重写 |
| 1.2 | 新增 `locale_resolver` 节点：检测 locale，缺失则回退到默认值 | `room_service_agent.py` | ➕ 新增 |
| 1.3 | chatbot 节点要求 LLM 输出结构化 JSON（intent + slots + entities） | `room_service_agent.py` | ⚠️ 改造 |
| 1.4 | 新增 `IntentCandidate` 数据模型 | 新建 `models.py` | ➕ 新增 |

---

## Phase 2：槽位提取 & 归一化（Slot Extraction）

### BRD 要求（§9 步骤 2-6）

对每个 intent，必须提取其 required + optional 槽位并归一化。

**你的槽位清单**（从 SlotDefinitions §8.3 提取，仅客房服务相关）：

| 槽位 | 范围 | 枚举值 | 用于 intent |
|------|------|--------|-------------|
| `request_type` | — | room_service, housekeeping, hotel_call, workorder, amenity, other | ROOM_SERVICE, HOUSEKEEPING, HOTEL_CALL |
| `details` | — | — | 三个服务 intent |
| `priority` | — | low, normal, high, urgent | 三个服务 intent |
| `location` | — | — | 三个服务 intent（房间号） |
| `alarm_action` | — | set, delete, close | ALARM |
| `time` | — | — | ALARM (HH:MM) |
| `duration` | 1.0–10080.0 | — | ALARM |
| `label` | — | — | ALARM |
| `repeat` | — | — | ALARM |
| `alarm_id` | — | — | ALARM delete/close |

### 现状 vs 需求

| BRD 要求 | 当前代码 | 差距 |
|----------|----------|------|
| 从用户消息中提取结构化槽位 | ⚠️ LLM 在 system prompt 指导下隐式提取，传给工具函数 | 需要显式提取 + 校验后再传工具 |
| `request_type` 枚举校验 | ❌ 无 | 工具函数按函数名隐式映射，需显式校验 |
| `priority` 默认值 | ❌ 无 | 默认应为 `normal` |
| `duration` 范围校验 [1, 10080] | ❌ 无 | 新增 |
| `time` 解析（HH:MM/口语） | ❌ 无 | 新增 `parse_time()` 工具函数 |
| 房间号提取 | ⚠️ LLM 隐式提取 | OK 但需校验房间号格式 |

### 行动项

| # | 行动 | 类型 |
|---|------|------|
| 2.1 | 新增 `slot_extractor` 节点：从 LLM 输出 JSON 中提取 slots | ➕ |
| 2.2 | 新增 `slot_validator` 节点：按 SlotDefinitions 做 enum/range 校验 | ➕ |
| 2.3 | 新增 `slot_normalizer`：vague → preset 映射（如"打扫"→request_type=housekeeping） | ➕ |
| 2.4 | 工具函数签名增加 `request_type` 参数，内部不再隐式推断 | ⚠️ 改造 |

---

## Phase 3：实体解析（Entity Resolution）

### BRD 要求（§10.3）

```
(1) 按 locale 匹配 variants
(2) 多 canonical 命中 → ambiguous_entity
(3) 无命中但意图需要 → entity_not_found
```

### 现状 vs 需求

| BRD 要求 | 当前代码 | 差距 |
|----------|----------|------|
| locale 匹配 | ❌ 无 | ❌ |
| 歧义检测 | ❌ 无 | ❌ |
| 实体缺失澄清 | ⚠️ system prompt 写了"没房间号就问" | 只是 prompt 引导，不是代码强制 |

### 行动项

| # | 行动 | 类型 |
|---|------|------|
| 3.1 | 新建 `entity_resolver` 节点：按 locale 查找 Lexicon | ➕ |
| 3.2 | 歧义/缺失 → 输出 `ambiguous_entity` / `entity_not_found` | ➕ |

> **注**：客房服务 Agent 的主要实体是房间号（location）和服务类型（request_type），不涉及 device_name/scene_name 等。本 Phase 可放在 Phase 5 之后再做，**优先级中**。

---

## Phase 4：能力矩阵 Gating（Capability Matrix）

### BRD 要求（§10.2）

```
service 设备类型支持的 intent_L1:
  ✅ HOTEL_CALL  ✅ HOUSEKEEPING  ✅ ROOM_SERVICE  ✅ NEED_CLARIFY  ✅ EXIT
  ❌ ALARM（alarm 在 CM_013 行，device_type=alarm）
```

### 现状 vs 需求

| BRD 要求 | 当前代码 | 差距 |
|----------|----------|------|
| 按 device_type 过滤 | ❌ 完全没有 | ❌ |
| unsupported → need_clarify/reject | ❌ 完全没有 | ❌ |

### 行动项

| # | 行动 | 类型 |
|---|------|------|
| 4.1 | 新建 `capability_gate` 节点：查 capability_matrix.json | ➕ |
| 4.2 | ALARM intent 归属 alarm 设备类型，不是 service | ➕ 配置 |
| 4.3 | gating 失败 → `capability_unsupported` | ➕ |

---

## Phase 5：风控红线（Risk Control）

### BRD 要求（§7 + §7.1）

**Intent 级红线**：

| intent_L1 | 风险 | 触发条件 | 要求 |
|-----------|------|----------|------|
| HOUSEKEEPING | 🔴 高 | 生成工单/服务请求 | 必须二次确认 |
| HOTEL_CALL | 🔴 高 | 拨打/转接可能产生费用 | 必须二次确认 |
| ROOM_SERVICE | 🔴 高 | 可能产生费用/工单 | 必须二次确认 |
| ALARM | 🟡 中 | delete/close 或长时长 | delete/close 必须二次确认 |

**全局红线 GR-01~GR-10**（§7.1）：

客房服务最相关的是 GR-03（高影响操作）、GR-06（时间解析失败）、GR-09（置信度不足）、GR-10（缺目标对象）。

### 现状 vs 需求

| BRD 要求 | 当前代码 | 差距 |
|----------|----------|------|
| Intent 级风险红线 | ❌ 完全缺失 | 所有3个服务 intent 都是高风险，当前直接执行不确认 |
| GR-03 不可逆操作确认 | ❌ 缺失 | ALARM delete/close 当前无二次确认 |
| NeedClarify 优先级排序 | ❌ 缺失 | |
| confirm_action 结构 | ❌ 缺失 | |
| 现有 guardrail（政治/黑客） | ⚠️ 存在但与 BRD 红线不同 | **保留但重命名**：这是内容安全护栏，不是 BRD 风控红线 |

### 行动项

| # | 行动 | 类型 |
|---|------|------|
| 5.1 | 新建 `risk_checker` 节点：检查 intent 风险等级 | ➕ |
| 5.2 | 高风险 + 未确认 → 输出 `risky_action_need_confirm` + `confirm_action` | ➕ |
| 5.3 | 实现 GR-01~GR-10 全局红线检查 | ➕ |
| 5.4 | 实现 NeedClarify 优先级排序（§6.1.6） | ➕ |
| 5.5 | 现有 guardrail（政治/黑客）重命名为 `content_safety_filter`，作为独立第一关 | ⚠️ 保留+重命名 |
| 5.6 | ALARM delete/close 操作触发二次确认 | ➕ |

---

## Phase 6：NeedClarify 结构化输出

### BRD 要求（§6 + §6.1）

```
result_type=need_clarify 时，必须输出：
  reason_code (必填)  — 来自 14 个标准原因码
  clarify_slot (必填) — 需用户补充的字段
  candidates (强烈建议)
  prompt_key (可选)
  target_intent (可选)
  confirm_action (风险场景必填)
```

### 现状 vs 需求

| BRD 要求 | 当前代码 | 差距 |
|----------|----------|------|
| 标准 reason_code 枚举 | ❌ 无 | 14 个原因码全部缺失 |
| 结构化输出格式 | ❌ 纯文本回复 | 需要 JSON 结构化 |
| candidates 标准结构 | ❌ 无 | |
| clarify_slot 枚举 | ❌ 无 | |
| confirm_action 结构 | ❌ 无 | 高风险场景必须提供 |

### 行动项

| # | 行动 | 类型 |
|---|------|------|
| 6.1 | 新建 `clarify_builder` 模块：生成标准 NeedClarify 响应 | ➕ |
| 6.2 | 实现 14 个 reason_code 枚举 | ➕ |
| 6.3 | 实现 candidates 标准结构 | ➕ |
| 6.4 | 实现 clarify_slot 枚举 | ➕ |

---

## Phase 7：决策输出 & Trace

### BRD 要求（§5.2 + §11）

```
最终输出：
  final_intent: {L1, L2, L3, ID}
  final_slots: {slot: canonical_value, ...}
  resolved_entities: {type: canonical, ...}
  result_type: "execute" | "need_clarify" | "reject"
  decision_trace: [step1, step2, ...]
```

### 现状 vs 需求

| BRD 要求 | 当前代码 | 差距 |
|----------|----------|------|
| 标准化输出格式 | ❌ 纯文本 | 需要标准化 JSON |
| result_type 三元决策 | ❌ | |
| decision_trace | ❌ 日志有但不结构化 | 需要结构化 trace |
| 配置版本号 | ❌ | |

### 行动项

| # | 行动 | 类型 |
|---|------|------|
| 7.1 | 新增 `DecisionTrace` 数据模型，记录每步（规则名/输入/输出/结果） | ➕ |
| 7.2 | 新增 `ResponseFormatter`：将内部状态转成标准输出 JSON | ➕ |
| 7.3 | FastAPI `/api/chat` 响应改为包含完整结构化输出 | ⚠️ 改造 |

---

## Phase 8：验收测试 & 监控

### BRD AC1-AC5（§11）

| AC | 要求 | 当前 |
|----|------|------|
| AC1 | 枚举值闭环 | ❌ |
| AC2 | 能力矩阵严格生效 | ❌ |
| AC3 | 槽位范围与 clamp | ❌ |
| AC4 | 缺失 required 槽 → need_clarify | ❌ |
| AC5 | 实体/动作可追溯 | ❌ |

### 行动项

| # | 行动 | 类型 |
|---|------|------|
| 8.1 | 为每条 AC 编写测试用例 | ➕ |
| 8.2 | 测试覆盖 4 个 intent 的 execute/need_clarify/reject 路径 | ➕ |

---

## 三、现有代码逐行判定

### `room_service_agent.py` — 核心图

| 行 | 内容 | 判定 | 说明 |
|----|------|------|------|
| 38-42 | State 定义 | ⚠️ | 需扩展：加 `result_type`, `decision_trace`, `locale`, `final_output` |
| 45-49 | load_system_prompt | ⚠️ | 保留，但 prompt 内容需重写 |
| 52-61 | get_rag_retriever | ✅ | 保留，知识库继续用 |
| 75-85 | guardrail_node | ⚠️ | 保留架构，改名为 `content_safety_filter`，关键词列表待扩展 |
| 88-91 | check_safety | ⚠️ | 路由名改为 `content_safety_check` |
| 93-98 | refuse_node | ⚠️ | 保留，但需输出结构化 `result_type=reject` |
| 101-106 | rag_node | ✅ | 保留 |
| 109-126 | chatbot_node | 🔴 | **核心改造点**：需注入 intent 定义、要求 JSON 输出、输出结构化意图+槽位 |
| 129-134 | should_continue | ⚠️ | 保留，但工具调用后需走校验流程而非直接回 chatbot |
| 141-168 | build_graph | 🔴 | **需大幅改造**：插入新节点（slot_validator, capability_gate, risk_checker 等） |
| 171-174 | MemorySaver | ✅ | 保留 |
| 179-201 | invoke_agent | ⚠️ | 保留，返回从纯文本改为结构化 |

### `tools_api/mock_services.py` — 工具函数

| 函数 | 判定 | 说明 |
|------|------|------|
| `order_room_service` | ⚠️ | 保留。加 `request_type` 参数。⚠️ 与点餐 Agent 边界待协商 |
| `request_cleaning` | ⚠️ | 保留。加 `request_type=housekeeping`, `priority`。返回值加 BRD trace |
| `request_supplies` | ⚠️ | 保留。加 `request_type=amenity`。需区分于 ROOM_SERVICE |
| `report_maintenance` | ⚠️ | 保留。加 `request_type=workorder` |
| `request_laundry` | ⚠️ | 保留。加 `request_type` 归属（HOUSEKEEPING 或 ROOM_SERVICE） |
| `set_wake_up_call` | ⚠️ | 保留。加 `alarm_action=set`。缺少 delete/close alarm 工具 |
| — | ❌ | **缺 `delete_alarm` 工具**（ALARM_002） |
| — | ❌ | **缺 `close_alarm` 工具**（ALARM_003） |
| — | ❌ | **缺 `call_hotel` 工具**（HOTEL_CALL intent） |

### `main_router.py` — 路由层

| 内容 | 判定 | 说明 |
|------|------|------|
| LLM 意图分类（classify_intent） | ✅ | 保留，5路分发架构合理 |
| 子 agent 调用 | ✅ | 保留 |
| State 定义 | ⚠️ | 需扩展，加结构化输出传递 |

### `prompts/system_prompt.txt` — 系统提示词

| 内容 | 判定 | 说明 |
|------|------|------|
| 工具使用铁律 | ⚠️ | 保留思路，但需加入 6 个 intent 的 BRD 定义 |
| 信息补全规则 | ⚠️ | 保留，但需要与 BRD required slot 对齐 |
| 回复要求 | ✅ | 保留 |
| 缺少 intent/slot 结构化定义 | 🔴 | **缺失**：需要注入 IntentDefinitions + SlotDefinitions |

---

## 四、完整实施计划（按优先级排序）

### 🔴 第一批（必须立即做）：配置落地 + 输出标准化

| 顺序 | 任务 | 预计工作量 | 产出 |
|------|------|-----------|------|
| **P0.1** | 新建 `config/` 目录，把 BRD §8 的 6 张表 JSON 化 | 2h | `general.json`, `intent_definitions.json`, `slot_definitions.json`, `capability_matrix.json`, `risk_control.json` |
| **P0.2** | 新建 `models.py` — 数据模型（IntentCandidate, Slot, DecisionTrace, NeedClarify, FinalOutput） | 1h | `models.py` |
| **P6.1** | 重写 `system_prompt.txt` — 注入 intent + slot 定义，要求 JSON 输出 | 1.5h | 新版 system prompt |
| **P6.2** | 改造 `chatbot_node` — 输出结构化 JSON（intent + slots + entities） | 2h | 改造 chatbot 节点 |
| **P7.1** | 实现 `ResponseFormatter` — 输出标准 JSON（execute/need_clarify/reject + trace） | 2h | `response_formatter.py` |

### 🟡 第二批（本周）: 校验链路

| 顺序 | 任务 | 预计工作量 | 产出 |
|------|------|-----------|------|
| **P1.1** | `slot_validator` 节点 — enum/range/required 校验 | 2h | 校验节点 |
| **P1.2** | `capability_gate` 节点 — 能力矩阵检查 | 1h | Gating 节点 |
| **P1.3** | `risk_checker` 节点 — 风控红线 + GR-01~10 | 3h | 风控节点 |
| **P1.4** | `clarify_builder` 模块 — NeedClarify 结构化生成 | 2h | 澄清模块 |
| **P1.5** | 改造 `build_graph()` — 插入全部新节点到图中 | 2h | 完整图 |

### 🟢 第三批（下周）: 工具对齐 + 测试

| 顺序 | 任务 | 预计工作量 | 产出 |
|------|------|-----------|------|
| **P2.1** | 工具函数改造 — 加 `request_type` 参数 + BRD trace | 2h | 改造后的 tools |
| **P2.2** | 新增 `delete_alarm` / `close_alarm` / `call_hotel` 工具 | 1.5h | 补齐工具 |
| **P2.3** | `locale_resolver` 节点 + `entity_resolver` 节点 | 2h | locale + 实体 |
| **P2.4** | 验收测试 — 写 AC1-AC5 测试用例 | 3h | 测试文件 |
| **P2.5** | 边界协商 — 与点餐 Agent 确认 `order_room_service` 归属 | 0.5h | 决策记录 |

---

## 五、删除/变更清单

### 🔴 需要删除的内容

| 文件 | 内容 | 原因 |
|------|------|------|
| `room_service_agent.py:76` | `dangerous_keywords = ["政治","黑客","写代码","入侵","暴力","色情","赌博"]` | 过于简陋，用 BRD 风控红线（GR-01~10）替代。保留 content_safety 概念但重构 |
| — | 整个 `order_room_service` 函数的"送餐"语义 | 与点餐 Agent 冲突。改为纯客房补给（饮料/果盘等非正餐物品），或明确标注为"边界待协商" |

### ⚠️ 需要改造的内容

| 文件 | 内容 | 改造成 |
|------|------|--------|
| `room_service_agent.py:38-42` | State 4 个字段 | → 新增 `result_type`, `decision_trace`, `locale`, `final_output`, `confirm_pending` |
| `room_service_agent.py:109-126` | chatbot_node | → 输出结构化 JSON；根据 intent 定义选择强制工具调用 |
| `room_service_agent.py:141-168` | build_graph | → 插入 6 个新节点到流水线 |
| `tools_api/mock_services.py:ALL` | 所有工具只返回文本 | → 返回 `{result, trace_info}` 结构 |
| `server.py:39-51` | ChatResponse 简单文本 | → 返回完整结构化输出 |
| `prompts/system_prompt.txt` | 只有工具使用指引 | → 新增意图定义表 + 槽位定义表 + 输出格式要求 |

### ➕ 需要新建的内容

| 文件 | 用途 |
|------|------|
| `models.py` | 全部数据模型定义 |
| `config/general.json` | language/device_type/location/scope 枚举 |
| `config/intent_definitions.json` | 6 条客房服务 intent |
| `config/slot_definitions.json` | 11 个槽位定义 |
| `config/capability_matrix.json` | service 能力矩阵 |
| `config/risk_control.json` | intent 级风险 + GR-01~10 |
| `slot_validator.py` | 槽位校验（enum/range/required） |
| `capability_gate.py` | 能力矩阵 Gating |
| `risk_checker.py` | 风控红线检查 |
| `clarify_builder.py` | NeedClarify 结构化构建 |
| `response_formatter.py` | 最终输出格式化 + trace |
| `locale_resolver.py` | locale 检测与回退 |
| `entity_resolver.py` | 实体解析 |
| `tests/test_room_service.py` | AC1-AC5 验收测试 |

---

## 六、改造后的完整 LangGraph 图

```
START
  │
  ▼
┌──────────────────┐
│ content_safety   │  ← 保留现有 guardrail，重命名
│ (政治/暴力等)     │
└──────┬───────────┘
       │ SAFE              │ UNSAFE → refuse → END
       ▼
┌──────────────────┐
│ locale_resolver  │  ← 新增：locale 检测 & 回退
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ rag_retrieve     │  ← 保留现有 RAG
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ chatbot          │  ← 改造：输出结构化 JSON {intents, slots, entities}
│ (LLM 意图+槽位)   │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ slot_validator   │  ← 新增：enum/range/required 校验
│ (按配置表校验)     │
└──────┬───────────┘
       │ valid              │ invalid → clarify_builder → END
       ▼
┌──────────────────┐
│ entity_resolver  │  ← 新增：实体标准化 + 歧义检测
└──────┬───────────┘
       │ resolved           │ ambiguous/not_found → clarify_builder → END
       ▼
┌──────────────────┐
│ capability_gate  │  ← 新增：能力矩阵检查
└──────┬───────────┘
       │ pass               │ blocked → clarify_builder → END
       ▼
┌──────────────────┐
│ risk_checker     │  ← 新增：风控红线 + GR-01~10
│ (intent级+全局)   │
└──────┬───────────┘
       │ safe               │ risky → 首次自动进入二次确认 / 已确认则放行
       ▼
┌──────────────────┐
│ tools / execute  │  ← 保留现有 ToolNode，改造返回值
│ (调用工具函数)     │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ response_        │  ← 新增：标准化输出 {result_type, final_intent, ...}
│ formatter +      │
│ decision_trace   │
└──────────────────┘
       │
       ▼
      END
```

---

## 七、关键决策记录

| # | 决策 | 理由 |
|---|------|------|
| 1 | `order_room_service` 暂时保留在你的 Agent 中 | 与点餐 Agent 的边界需和 PM 确认。BRD §12 FoodAgent 有独立工具体系，你的 ROOM_SERVICE intent 侧重"送物品到房间"而非"点菜"。**建议**：送饮料/果盘/零食保留在此；正餐点菜走 FoodAgent |
| 2 | ALARM 的 device_type 是 `alarm` 不是 `service` | CapabilityMatrix CM_013 行明确。你的 Agent 处理 ALARM 时需用 alarm 设备类型做 gating |
| 3 | 风控红线不替代内容安全护栏 | BRD 的风控红线（GR-01~10）是关于"操作安全性"（费用/工单/不可逆），现有的内容安全（政治/色情）是不同维度，两者都应保留 |
| 4 | MemorySaver 当前够用 | BRD 要求退房后清除会话（`DELETE /api/sessions/{id}`），MemorySaver 重启即清，符合要求。等正式上线前再升级 SqliteSaver |

---

## 八、总时间估算

| 批次 | 内容 | 预估工时 |
|------|------|----------|
| 🔴 第一批 | 配置 JSON + 模型定义 + prompt 重写 + 输出标准化 | **8.5h** |
| 🟡 第二批 | 校验链路（slot/capability/risk/clarify）+ 图改造 | **10h** |
| 🟢 第三批 | 工具对齐 + locale/entity + 测试 | **9h** |
| **总计** | | **~27.5h（约 1 周）** |

---

*文档结束。后续按批次顺序实施，每完成一个 Phase 跑一次集成测试确认。*
