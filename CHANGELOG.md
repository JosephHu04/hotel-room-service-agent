# Changelog

All notable changes to the Hotel Room Service Agent project.

---

## v3.0.0 — 本地化 + 精简架构 (2025-06-16)

### 🎯 总览

v3 是一次**架构精简 + 本地化部署**的重大升级。核心思路：信任 LLM 的判断力，去掉冗余节点；拥抱本地 Ollama，零成本运行。

| 指标 | v2 | v3 | 变化 |
|------|----|----|------|
| 图节点数 | 4 | 2 | **-50%** |
| State 字段 | 5 | 2 | **-60%** |
| LLM 调用/请求 | 2-3 次 | 1 次 | **延迟减半** |
| RAG 外部依赖 | Chroma + HuggingFace | 纯 Python 标准库 | **零依赖** |
| API 成本 | 按 Token 付费 | **免费** | 本地运行 |

### 🚀 重大变更

#### LLM: DeepSeek API → Ollama 本地
- 🔌 从云端 DeepSeek (`deepseek-chat`) 切换到本地 Ollama (`qwen3:8b`)
- 💰 零 API 成本，无需网络
- 🔒 客人数据不出本地，隐私更安全
- 🔄 支持任意 Ollama 模型热切换

#### 架构: 4 节点 → 2 节点
- ❌ 移除 `safety_check_node` — LLM 安全检查（合并到 System Prompt）
- ❌ 移除 `safety_refuse_node` — 拒绝回复生成（Agent 自行处理）
- ❌ 移除 `logic_check_node` — LLM 逻辑检查（Agent 自行判断）
- ❌ 移除 `logic_guide_node` — 引导回复生成（Agent 自行处理）
- ⚡ 每次请求 LLM 调用从 2-3 次减少到 1 次

#### RAG: Chroma + HuggingFace → 纯 Python TF-IDF
- 🪶 移除 `langchain-chroma`、`sentence-transformers`、`langchain-huggingface` 依赖
- 🚫 不再需要下载 ~90MB 的 `all-MiniLM-L6-v2` 嵌入模型
- 🐍 纯 Python 标准库实现：中文分词 → TF-IDF 向量 → 余弦相似度
- ⚡ 启动即刻可用，零下载

#### State 精简: 5 字段 → 2 字段
- ❌ 移除 `is_safe`、`logic_result`、`logic_note` 字段
- ✅ 保留 `messages`（对话历史）+ `context`（RAG 检索结果）

### ✨ 新增功能

#### 💾 JSON 对话持久化
- `_load_sessions()` — 启动时自动从 `conversations.json` 恢复历史对话
- `_save_sessions()` — 每次对话后自动保存
- 🔄 服务器重启对话不丢失

#### 🛡️ 房间号校验
- 新增 `_check_room()` 函数，防止 LLM 编造房间号
- 覆盖 5 个需要房间号的工具函数
- 拒绝空值、`N/A`、过长（>6位）、纯字母

#### 📊 性能测试套件
- 新增 `test_performance.py`，6 维度自动化测试：
  - RAG 检索速度 (ms)
  - 端到端延迟 (s)
  - Token 生成速度 (tok/s)
  - 工具调用准确率 (%)
  - 边界拒绝准确率 (%)
  - 追问准确率 (%)

#### 🔧 ChatResponse 新增 tool_calls 字段
- API 响应现在包含本轮调用的工具列表
- 便于前端展示和调试监控

#### 📝 System Prompt 增强
- 新增「半句对半句错」混合内容处理规则
- 新增「房间号铁律」（不编造、以最新为准）
- 新增「客人否认/纠正」处理流程

### ❌ 移除
- `tools_api/__init__.py`
- `safety_llm` 独立 LLM 实例
- `SAFETY_CHECK_PROMPT` 和 `LOGIC_CHECK_PROMPT`
- Chroma 向量数据库 + HuggingFace Embeddings 依赖

### 📁 结构调整
- `backend/` → `agent主体框架/`
- `web-ui/` → `ui界面文件/`

---

## v2.0.0 — ReAct Agent 重构 (2025-06-11)

### 🎯 总览
从 v1 的 12 节点帧基对话系统重构为 4 节点 ReAct Agent。

### 🚀 重大变更
- 🏗️ 架构: 12 节点流水线 → 4 节点 ReAct Agent (Safety→Logic→RAG→Agent⇄Tools)
- 🧠 LLM 角色: JSON 提取器 → 系统决策大脑
- ✂️ 代码: ~3,000 行 → ~500 行
- 🔧 意图识别: 硬编码映射表 → LLM 自主理解
- 💬 追问: 模板拼接 → LLM 自然语言生成
- 🎯 工具选择: `INTENT_TOOL_MAP` 查表 → LLM 自主选择
- 🔍 RAG: 新增 Chroma + HuggingFace 向量检索
- 🛡️ 安全: 新增 LLM 安全检查 + 逻辑检查节点

### 🛠️ 工具
- 8 个 mock 工具函数，覆盖客房服务全部场景
- 与 BRD 意图枚举对齐

---

## v1.0.0 — 初始版本 (2025-06-09)

### 初始架构
- 12 节点帧基对话系统 (Frame-based DSL)
- 硬编码意图映射 + 槽位校验 + 模板回复
- ~3,000 行代码
