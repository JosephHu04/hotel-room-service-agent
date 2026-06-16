"""
酒店客房服务 Agent — ReAct 模式
==============================================
架构: LangGraph (RAG + Agent ⇄ Tools)

Agent 模式: LLM 自主决策
  - LLM 是大脑：理解意图、判断信息完整性、选择工具、追问/执行
  - 工具是双手：8 个 mock 工具函数，挂载在 agent 外面
  - 代码只做两件事：安全底线 + 路由

ReAct 循环: Thought → Action → Observation → Thought → ... → Final Answer
"""

# ============================================================
# import：引入外部库（Python 的 #include）
# ============================================================
import os                                                        # 操作系统相关：读文件路径
import json                                                       # JSON：对话记录持久化
import logging                                                   # 日志：记录 agent 每一步做了什么
import re                                                         # 正则：分词用

from typing import Annotated                                     # 类型标注：告诉 Python State 里字段怎么合并
from typing_extensions import TypedDict                          # 类型标注：定义 State 的结构（有哪些字段）

# --- LangGraph：编排框架（搭图、连边、编译、运行） ---
from langgraph.graph import StateGraph, START, END               # StateGraph: 搭图 | START/END: 图的起点终点
from langgraph.graph.message import add_messages                 # add_messages: 新消息追加到历史，不覆盖
from langgraph.prebuilt import ToolNode                          # ToolNode: 把工具函数自动包装成图节点
from langgraph.checkpoint.memory import MemorySaver              # MemorySaver: 内存对话记忆

# --- LangChain：消息类型 + LLM 客户端 ---
from langchain_core.messages import HumanMessage, SystemMessage
#   HumanMessage  = 用户说的话
#   SystemMessage = 系统指令（System Prompt）

from langchain_openai import ChatOpenAI                          # LLM 客户端：Ollama OpenAI 兼容接口

# --- 8 个工具函数（mock_services.py） ---
from tools_api.mock_services import ALL_TOOLS                    # 工具列表：request_supplies, request_cleaning, ...

# ============================================================
# 日志配置
# ============================================================
logging.basicConfig(
    level=logging.INFO,                                          # INFO 级别：正常流程都记录
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s", # 格式：时间 [级别] 模块名 - 消息
    datefmt="%Y-%m-%d %H:%M:%S",                                 # 时间格式：年-月-日 时:分:秒
)
logger = logging.getLogger("RoomServiceAgent")                   # 创建本模块专属的 logger


# ============================================================
# 第一部分：State — Agent 的"草稿纸"
# ============================================================
# State 是一个字典，在图的各个节点之间流转。
# 每个节点读取 State、处理、返回更新后的 State。
# 整个对话过程中，State 始终保持，就像一张贯穿全流程的草稿纸。

class State(TypedDict):
    """Agent 内部状态 — 只有 2 个字段"""
    messages: Annotated[list, add_messages]   # 对话历史（用户消息 + AI 回复 + 工具调用结果）
    context: str                               # RAG 检索到的知识库文本


# ============================================================
# System Prompt 构造函数
# ============================================================

def build_system_prompt(rag_context: str = "") -> str:
    """加载缓存的 System Prompt，有 RAG 知识则拼在末尾"""
    if rag_context:
        return _base_prompt + f"\n\n【酒店知识库参考】\n{rag_context}"
    return _base_prompt


# ============================================================
# 纯 Python RAG：TF-IDF 向量检索器，零外部依赖
# ============================================================

class SimpleRetriever:
    """
    TF-IDF 向量检索器，纯 Python 实现。
    流程：分词 → TF-IDF 向量化 → 余弦相似度匹配。
    不需要 Chroma、HuggingFace、numpy——只用标准库。
    """

    def __init__(self, knowledge_path: str):
        with open(knowledge_path, "r", encoding="utf-8") as f:
            text = f.read()
        self.chunks = [c.strip() for c in text.split("\n\n") if c.strip()]
        self.vocab, self.idf, self.chunk_vecs = self._build_index()

    def _tokenize(self, text: str) -> list:
        """中文分词：按非中文字符切割，保留长度>=1的词"""
        words = re.split(r"[^一-鿿a-zA-Z0-9]+", text)
        return [w.lower() for w in words if len(w) >= 1]

    def _build_index(self):
        """构建倒排索引：词表 + IDF + 每条文档的 TF-IDF 向量"""
        # 1. 统计每个词出现过的文档数（DF）
        doc_count = len(self.chunks)
        df = {}  # word → 出现在几个文档里
        doc_words = []  # 每条文档的词列表

        for chunk in self.chunks:
            words = self._tokenize(chunk)
            doc_words.append(words)
            for w in set(words):
                df[w] = df.get(w, 0) + 1

        # 2. 构建词表（按字母排序，保证位置固定）
        vocab = sorted(df.keys())

        # 3. 算 IDF
        import math
        idf = {w: math.log((doc_count + 1) / (df[w] + 1)) + 1 for w in vocab}

        # 4. 每条文档的 TF-IDF 向量（存成 dict，稀疏表示）
        vecs = []
        for words in doc_words:
            tf = {}  # 词频
            for w in words:
                tf[w] = tf.get(w, 0) + 1
            vec = {w: (tf[w] / len(words)) * idf[w] for w in tf}
            vecs.append(vec)

        return vocab, idf, vecs

    def _query_vec(self, query: str) -> dict:
        """查询文本 → TF-IDF 向量"""
        words = self._tokenize(query)
        if not words:
            return {}
        tf = {}
        for w in words:
            if w in self.idf:  # 只看词表内的词
                tf[w] = tf.get(w, 0) + 1
        return {w: (tf[w] / len(words)) * self.idf[w] for w in tf}

    def _cosine(self, a: dict, b: dict) -> float:
        """两个稀疏向量的余弦相似度"""
        if not a or not b:
            return 0.0
        dot = sum(a.get(k, 0) * b.get(k, 0) for k in set(a) & set(b))
        norm_a = sum(v ** 2 for v in a.values()) ** 0.5
        norm_b = sum(v ** 2 for v in b.values()) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def invoke(self, query: str) -> list:
        """搜索：查询向量 × 每条文档向量 → 余弦相似度 → 返回最高分文档"""
        qv = self._query_vec(query)

        if not qv:
            top = self.chunks[0] if self.chunks else ""
        else:
            best_score, best_chunk = -1, self.chunks[0]
            for i, dv in enumerate(self.chunk_vecs):
                s = self._cosine(qv, dv)
                if s > best_score:
                    best_score, best_chunk = s, self.chunks[i]
            top = best_chunk if best_score > 0 else self.chunks[0]

        Doc = type('Doc', (), {})
        doc = Doc()
        doc.page_content = top
        return [doc]


def get_rag_retriever():
    """初始化纯 Python TF-IDF 检索器"""
    knowledge_path = os.path.join(os.path.dirname(__file__), "knowledge", "placeholder_info.txt")
    return SimpleRetriever(knowledge_path)


# ============================================================
# 第二部分：配置 & LLM 初始化
# ============================================================

OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "qwen3:8b"

# 缓存 System Prompt，启动时读一次
_base_prompt = ""
_prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.txt")
if os.path.exists(_prompt_path):
    with open(_prompt_path, "r", encoding="utf-8") as _f:
        _base_prompt = _f.read()

# --- LLM 实例 ---
llm_with_tools = ChatOpenAI(
    model=OLLAMA_MODEL,
    temperature=0.5,
    max_tokens=256,                       # 客房回复简短，256 足够
    top_p=0.85,                           # 过滤离谱选词，保持回复稳定
    api_key="ollama",
    base_url=OLLAMA_BASE_URL,
    # repeat_penalty 不被 Ollama OpenAI 接口支持，已移除
).bind_tools(ALL_TOOLS)

# --- 初始化 RAG 检索器（全局变量，启动时执行一次） ---
retriever = get_rag_retriever()

logger.info("LLM 已初始化: %s (Ollama 本地, 工具数=%d)", OLLAMA_MODEL, len(ALL_TOOLS))
logger.info("可用工具: %s", [t.name for t in ALL_TOOLS])


# ============================================================
# 第三部分：图节点 — 每一步做什么
# ============================================================
# 每个节点都是一个 Python 函数，输入 State，返回 State 的部分更新

# --- 节点 1：RAG 知识检索 ---
def rag_node(state: State) -> dict:
    """
    拿客人的消息去知识库搜索最相关知识。
    内部流程: 客人消息 → TF-IDF 向量 → 余弦相似度 → 最匹配段落 → 写入 context
    """
    last_message = state["messages"][-1].content               # 取客人最后一句话
    docs = retriever.invoke(last_message)                       # ★ 向量相似度检索
    # docs 是一个列表，每个元素有 .page_content 属性（原文）
    context_str = "\n".join([d.page_content for d in docs])    # 拼接所有检索结果
    logger.info("RAG 检索完成，上下文长度: %d 字符", len(context_str))
    return {"context": context_str}                             # 写入 state.context


# --- 节点 2：★ Agent 大脑 ★ ---
def agent_node(state: State) -> dict:
    """
    整个 Agent 最核心的节点。LLM 在这里做所有决策。

    流程:
      1. 构造 System Prompt（角色 + RAG 知识）
      2. 把 System Prompt + 对话历史一起发给 LLM
      3. LLM 返回 response，可能是：
         - 纯文本 → 对话结束
         - tool_calls → 需要执行工具

    LLM 自己判断:
      - 信息够不够（要不要追问）
      - 选哪个工具
      - 高风险操作要不要先确认
      - 怎么回复客人
    """
    # 构造 System Prompt（模板 + RAG 知识）
    sys_prompt = build_system_prompt(state.get("context", ""))

    # 构造消息列表：[SystemMessage, ...历史消息...]
    # [X] + [A, B, C] = [X, A, B, C] — Python 列表拼接
    # 只保留最近 20 条消息（约 10 轮对话），防止上下文过长
    MAX_HISTORY = 20
    history = state["messages"][-MAX_HISTORY:] if len(state["messages"]) > MAX_HISTORY else state["messages"]
    if len(state["messages"]) > MAX_HISTORY:
        logger.info("历史消息截断: %d条 → 保留最近%d条", len(state["messages"]), MAX_HISTORY)
    messages = [SystemMessage(content=sys_prompt)] + history

    # ★ 调 LLM（本地 Ollama）
    response = llm_with_tools.invoke(messages)

    # 日志：记录 LLM 做了什么决定
    if hasattr(response, "tool_calls") and response.tool_calls:
        # LLM 决定调工具
        for tc in response.tool_calls:
            logger.info("Agent 决策: 调用工具 %s(%s)", tc["name"], tc.get("args", {}))
    else:
        # LLM 决定直接回复
        reply_preview = (response.content or "")[:80] if hasattr(response, "content") else ""
        logger.info("Agent 决策: 直接回复 — %s", reply_preview)

    return {"messages": [response]}                            # 追加 LLM 回复到历史


# --- 路由函数 B：继续调工具？结束？ ---
def should_continue(state: State) -> str:
    """
    检查 LLM 的回复是否包含 tool_calls：
      有 tool_calls → "tools"（执行工具，然后回到 agent）
      没有         → "__end__"（对话结束，返回给客人）

    这是整个 ReAct 循环的控制器。代码不做决策——
    只看 LLM 有没有说要调工具。
    """
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "__end__"


# ============================================================
# 第四部分：搭图 — 把节点连成流程
# ============================================================

def build_graph():
    """
    用 LangGraph 搭有向图。

    图的流转:
        START → RAG → agent ⇄ tools → END
    """
    graph_builder = StateGraph(State)

    graph_builder.add_node("rag_retrieve", rag_node)
    graph_builder.add_node("agent", agent_node)
    graph_builder.add_node("tools", ToolNode(ALL_TOOLS))

    graph_builder.add_edge(START, "rag_retrieve")
    graph_builder.add_edge("rag_retrieve", "agent")

    graph_builder.add_conditional_edges(
        "agent", should_continue,
        {"tools": "tools", "__end__": END}
    )
    graph_builder.add_edge("tools", "agent")

    return graph_builder


# --- 编译图 + 绑定记忆 ---
MEMORY_FILE = os.path.join(os.path.dirname(__file__), "conversations.json")
agent_memory = MemorySaver()
room_service_graph = build_graph().compile(checkpointer=agent_memory)


# ============================================================
# JSON 文件持久化：启动时加载，每次对话后自动保存
# ============================================================
def _load_sessions():
    """从 JSON 文件恢复历史对话到 MemorySaver"""
    if not os.path.exists(MEMORY_FILE):
        return
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        for thread_id, messages in saved.items():
            config = {"configurable": {"thread_id": thread_id}}
            try:
                room_service_graph.update_state(config, {"messages": [
                    HumanMessage(content=m["content"]) if m["role"] == "user" else
                    SystemMessage(content=m["content"])
                    for m in messages
                ]})
            except Exception:
                pass
        logger.info("已从文件恢复 %d 个会话", len(saved))
    except Exception as e:
        logger.warning("会话恢复失败: %s", str(e))


def _save_sessions():
    """把当前活跃会话写入 JSON 文件"""
    try:
        # 只保存有实际对话的 session
        snapshots = {}
        for thread_id in _active_sessions:
            config = {"configurable": {"thread_id": thread_id}}
            try:
                state = room_service_graph.get_state(config)
                if state.values:
                    msgs = state.values.get("messages", [])
                    snapshots[thread_id] = [
                        {"role": "user" if isinstance(m, HumanMessage) else "assistant",
                         "content": m.content}
                        for m in msgs if hasattr(m, "content") and m.content
                    ]
            except Exception:
                pass
        if snapshots:
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(snapshots, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("会话保存失败: %s", str(e))


_active_sessions = set()
_load_sessions()  # 启动时恢复
# compile() = 把图"编译"成可执行状态
# checkpointer=agent_memory = 每个 session 自动保存/恢复对话历史

logger.info("Agent 图编译完成 (RAG → agent ⇄ tools)")


# ============================================================
# 第五部分：对外接口
# ============================================================

def invoke_agent_structured(message: str, session_id: str = "default") -> dict:
    """
    结构化调用接口。返回 {response_text, session_id, tool_calls}。
    server.py 用这个接口，invoke_agent 也基于此。
    """
    config = {"configurable": {"thread_id": session_id}}
    try:
        prev_state = room_service_graph.get_state(config)
        prev_msg_count = len(prev_state.values.get("messages", [])) if prev_state.values else 0

        result = room_service_graph.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=config,
        )
        reply = result["messages"][-1].content

        # 只看本轮新消息中的工具调用，不碰历史
        tool_calls_made = []
        new_msgs = result.get("messages", [])[prev_msg_count:]
        for msg in new_msgs:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls_made.append({"tool": tc["name"], "args": tc.get("args", {})})

        _active_sessions.add(session_id)
        _save_sessions()  # 每次对话后自动持久化
        logger.info("会话[%s] 回复 (工具=%d)", session_id, len(tool_calls_made))
        return {"response_text": reply, "session_id": session_id, "tool_calls": tool_calls_made}
    except Exception as e:
        logger.error("会话[%s] 异常: %s", session_id, str(e), exc_info=True)
        return {
            "response_text": "非常抱歉，系统暂时遇到了一些问题。请致电前台（电话：0000），我们的工作人员会立即为您处理。",
            "session_id": session_id, "tool_calls": [],
        }


def invoke_agent(message: str, session_id: str = "default") -> str:
    """最简调用接口，返回纯文本回复。内部调用 invoke_agent_structured。"""
    return invoke_agent_structured(message, session_id)["response_text"]


def clear_session(session_id: str) -> bool:
    """清除指定会话，从内存和 JSON 文件同时删除。"""
    _active_sessions.discard(session_id)
    _save_sessions()
    logger.info("会话[%s] 已清除", session_id)
    return True


# ============================================================
# 第六部分：Gradio 本地测试界面
# ============================================================
# 运行方式: python room_service_agent.py
# 然后在浏览器打开 http://127.0.0.1:7860

if __name__ == "__main__":
    # if __name__ == "__main__" 是什么意思？
    #   当这个文件被直接运行时（python room_service_agent.py），__name__ 就是 "__main__"
    #   当这个文件被 import 时（from room_service_agent import ...），__name__ 是 "room_service_agent"
    #   所以 if 块内的代码只在直接运行时执行，被 import 时不执行

    import gradio as gr

    def chat_interface(user_message, history):
        """Gradio 回调函数：用户发消息 → 调 agent → 返回回复"""
        return invoke_agent(user_message, session_id="gradio_demo")

    with gr.Blocks(title="客房服务 Agent — ReAct") as demo:
        gr.Markdown("## 客房服务 Agent（ReAct 模式）")

        chatbot = gr.Chatbot(height=520)
        msg = gr.Textbox(placeholder="描述您的需求...", show_label=False)

        def respond(message, history):
            reply = invoke_agent(message, session_id="gradio_demo")
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply})
            return "", history

        msg.submit(respond, inputs=[msg, chatbot], outputs=[msg, chatbot])

        gr.Examples(
            examples=[
                "送两瓶矿泉水和一条毛巾到8012",
                "8005的空调不制冷了，快来看看",
                "帮我预约明早7点的叫醒服务，房间8008",
                "我有一件西装需要干洗，在8015房",
            ],
            inputs=msg,
        )

    demo.launch(inbrowser=False, share=False)                    # inbrowser=False: 不自动弹浏览器
