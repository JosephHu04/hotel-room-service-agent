# prompts/ — LLM 提示词

---

## 这个文件夹是干什么的？

用一句话理解：**这里放的是 Agent 的"话术脚本"和"工作手册"。**

LLM 本身是一个通用模型，不知道"酒店客房服务 Agent"应该怎么说话、不知道有哪些意图、不知道什么时候必须调用工具。这个文件夹的两个文件配合起来，告诉 LLM 这一切——读完 prompt 之后，LLM 就"变身"成了你的客房服务 Agent。

---

## 两个文件的分工

```
system_prompt.txt        prompt_loader.py
      │                        │
      │  静态部分               │  动态部分
      │  角色、规则、话术       │  从 config/ JSON 自动读取
      │  改行为时改这个         │  改业务规则时改 JSON，不用动代码
      │                        │
      └────────┬───────────────┘
               │
               ▼
        完整的 System Prompt
        （每次启动自动拼装）
               │
               ▼
           发给 LLM
```

| 文件 | 管什么 | 什么时候改 | 举例 |
|------|--------|-----------|------|
| `system_prompt.txt` | 角色身份、核心规则、意图判定关键词、安全边界 | 调整 Agent 行为/话术/边界 | "客人说XX坏了→报修" |
| `prompt_loader.py` | 从 config JSON 读取意图表、槽位表、工具铁律、JSON 格式要求，拼装进 prompt | 基本不用改，业务规则改 config JSON 即可 | — |

---

## system_prompt.txt 的内容结构（已完成）

当前版本包含以下内容（均为静态内容，不依赖 JSON）：

### 1. 角色身份
```
你是五星级酒店客房服务 Agent，专门处理客人入住期间的客房相关需求。
- 专属管家，态度温和、礼貌、贴心
- 前台电话 0000
- 负责：物品补给、清洁打扫、报修维护、洗衣服务、呼叫前台、叫醒闹钟
- 不负责：送餐/点餐、入住/退房、周边旅游/叫车
```

### 2. 意图判定关键规则
告诉 LLM 怎么从客人话术判断意图，例如：
- "送XX"、"拿XX" → ROOM_SERVICE（物品补给）
- "打扫"、"做卫生" → HOUSEKEEPING + housekeeping（清洁）
- "XX坏了"、"XX不制冷" → HOUSEKEEPING + workorder（报修）
- "洗衣"、"干洗" → HOUSEKEEPING + amenity（洗衣）
- "叫醒"、"闹钟" → ALARM
- "叫前台"、"转人工" → HOTEL_CALL

### 3. 核心行为规则
- 缺必要信息要主动追问，不自己猜
- 不知道的事让客人联系前台
- 绝不回答酒店服务以外的问题

---

## prompt_loader.py 负责的动态部分（已完成）

txt 里有一行分割线：`（以下内容由 prompt_loader.py 从 config/ JSON 自动加载）`

这行之后的内容（6 个部分）全部由 prompt_loader.py 在启动时动态生成：

| # | 部分 | 来源 | 说明 |
|---|------|------|------|
| 1 | 意图定义表 | `config/intent_definitions.json` | 6 条意图的 L1/L2/L3/ID/required/optional/风险等级/例句 |
| 2 | 槽位说明表 | `config/slot_definitions.json` | 11 个槽位的类型/enum/range/default/format 校验规则 |
| 3 | 工具调用铁律 | 硬编码在 `_format_tool_rules()` | 什么场景必须调什么工具 |
| 4 | JSON 输出格式 | 硬编码在 `_build_json_output_instruction()` | 强制 LLM 输出 `{intents, slots, entities}` 的 JSON Schema |
| 5 | 语言设置 | `config/general.json` | 支持的语言列表和默认语言 |
| 6 | 知识库参考（可选） | RAG 检索结果 | `load_system_prompt_with_rag()` 时附加 |

---

## 核心设计原则

| 原则 | 说明 |
|------|------|
| **动静分离** | txt 管行为约束（改 Agent 话术时改），py 管业务数据（改业务规则时改 JSON） |
| **SSOT** | 意图/槽位定义只存在于 config JSON，prompt 自动同步，不存在"改了 JSON 忘记改 prompt"的问题 |
| **强制 JSON** | `format="json"` 让 LLM 必须输出结构化数据，下游代码解 JSON 而非解自然语言 |
| **可追溯** | prompt 每次启动时拼装，日志里能看到完整 prompt 长度 |

---

## 一次完整的 prompt 拼装过程

```python
# 1. prompt_loader.load_system_prompt() 被调用
# 2. 读取 system_prompt.txt（静态模板）
# 3. 读取 config/intent_definitions.json → 格式化成意图表
# 4. 读取 config/slot_definitions.json → 格式化成槽位表
# 5. 拼工具铁律 + JSON 格式要求
# 6. 读取 config/general.json → 拼语言设置
# 7. 全部拼接 → 返回完整 prompt 字符串（约 6000+ 字符）

# 如果有 RAG 上下文：
# 8. 在 prompt 末尾附加知识库参考文本
```

---

## 如何修改

| 想改什么 | 改哪里 |
|---------|--------|
| 加一种新意图（如"叫车"） | `config/intent_definitions.json` + `config/slot_definitions.json` |
| 改 request_type 的枚举值 | `config/slot_definitions.json` 中 SL_039 的 enum 列表 |
| 调整 Agent 的语气/话术风格 | `system_prompt.txt` 的角色定义部分 |
| 让 LLM 更好地区分某两种意图 | `system_prompt.txt` 的意图判定规则部分 |
| 改某个槽位的默认值 | `config/slot_definitions.json` 中对应槽位的 default 字段 |
| 增加/减少工具 | `tools_api/mock_services.py` + `prompt_loader.py` 的 `_format_tool_rules()` |
