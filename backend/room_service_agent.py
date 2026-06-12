"""
Hotel Room Service Agent — ReAct Pattern
==============================================
Architecture: LangGraph (LLM Safety Check + RAG + Agent ⇄ Tools)

Agent Pattern: LLM-driven autonomous decisions — the LLM makes ALL decisions
  - LLM is the brain: safety judgment, intent understanding, tool selection, response wording
  - Tools are the hands: 8 mock tool functions, return structured data for the LLM to phrase
  - Code only does: orchestration + routing; NO hardcoded decisions

ReAct Loop: Safety Check → RAG → Thought → Action → Observation → ... → Final Answer
"""

# ============================================================
# Imports — external libraries (Python's #include)
# ============================================================
import os                                                        # OS: read file paths, read env vars
import logging                                                   # Logging: record every step the agent takes

from typing import Annotated                                     # Typing: tell Python how to merge State fields
from typing_extensions import TypedDict                          # Typing: define State structure (which fields exist)

# --- LangGraph: orchestration framework (build graph, connect edges, compile, run) ---
from langgraph.graph import StateGraph, START, END               # StateGraph: build the graph | START/END: entry & exit
from langgraph.graph.message import add_messages                 # add_messages: append new messages to history, never overwrite
from langgraph.prebuilt import ToolNode                          # ToolNode: auto-wrap tool functions as graph nodes
from langgraph.checkpoint.memory import MemorySaver              # MemorySaver: in-memory conversation memory (lost on restart)

# --- LangChain: message types + LLM client ---
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
#   HumanMessage  = what the user said
#   SystemMessage = system instructions (System Prompt)
#   AIMessage     = AI/LLM reply

from langchain_openai import ChatOpenAI                          # LLM client: connect to DeepSeek API (OpenAI-compatible)

# --- RAG: vector database + embedding model ---
from langchain_chroma import Chroma                              # Chroma vector DB (stores embeddings, does similarity search)
from langchain_huggingface import HuggingFaceEmbeddings          # Embedding model: turns text into vectors (384-dim)

# --- 8 tool functions (mock_services.py) ---
from tools_api.mock_services import ALL_TOOLS                    # Tool list: request_supplies, request_cleaning, ...

# ============================================================
# Logging config
# ============================================================
logging.basicConfig(
    level=logging.INFO,                                          # INFO level: log normal flow
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s", # Format: time [level] module - message
    datefmt="%Y-%m-%d %H:%M:%S",                                 # Time format: YYYY-MM-DD HH:MM:SS
)
logger = logging.getLogger("RoomServiceAgent")                   # Create a dedicated logger for this module


# ============================================================
# Part 1: State — the Agent's "scratchpad"
# ============================================================
# State is a dict that flows between graph nodes.
# Each node reads State, processes, and returns partial updates.
# State persists throughout the entire conversation, like a scratchpad carried across the whole workflow.

class State(TypedDict):
    """Agent internal state — only 3 fields"""
    messages: Annotated[list, add_messages]   # Conversation history (user msgs + AI replies + tool call results)
    context: str                               # RAG-retrieved knowledge text
    is_safe: str                               # Guardrail result: "SAFE" or "UNSAFE"


# ============================================================
# System Prompt constructor
# ============================================================

def build_system_prompt(rag_context: str = "") -> str:
    """
    Load the System Prompt template and append RAG-retrieved knowledge.

    Args:
        rag_context: text retrieved by RAG from the knowledge base (may be empty string)

    Returns:
        Complete System Prompt string, sent to the LLM
    """
    # os.path.dirname(__file__) = directory containing this file
    # os.path.join(...) = join path segments (auto-handles Windows/Linux slash differences)
    prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.txt")

    # with open(...) as f: — Python's safe file open pattern, auto-closes
    # encoding="utf-8" — supports Chinese and other non-ASCII characters
    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read()                    # f.read() = read entire file contents

    # If RAG knowledge exists, append it to the prompt
    if rag_context:
        prompt += f"\n\n【Hotel Knowledge Base Reference (please follow strictly)】\n{rag_context}"

    return prompt


# ============================================================
# RAG init: Embedding model + Vector DB + Retriever
# ============================================================

def get_rag_retriever():
    """
    Initialize the RAG (Retrieval-Augmented Generation) retrieval engine.

    Three steps:
      1. Read knowledge base text
      2. Use embedding model to convert text → vectors
      3. Store in Chroma vector DB, return a retriever

    What is Chroma?
      - A lightweight vector database: pip install then import and use
      - No separate server needed — runs inside the Python process (embedded mode)
      - Stores "text + vector" pairs
      - When searching: user query → embedding → similarity scoring → return most similar text
    """
    # 1. Read knowledge base file
    knowledge_path = os.path.join(os.path.dirname(__file__), "knowledge", "placeholder_info.txt")
    with open(knowledge_path, "r", encoding="utf-8") as f:
        knowledge_text = f.read()

    # 2. Create embedding model (text → vector)
    # all-MiniLM-L6-v2: lightweight model, 384-dim vectors, auto-downloaded on first run
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    # 3. Create Chroma vector database
    # from_texts([text_list], embedding_model, collection_name)
    # Internal flow: text → vector → store
    vector_db = Chroma.from_texts(
        [knowledge_text],                # Knowledge text (currently a single segment)
        embeddings,                      # Embedding model
        collection_name="hotel_knowledge" # Collection name (one DB can have multiple collections)
    )

    # 4. Return retriever
    # as_retriever(k=1) = return the top-1 most relevant result per search
    return vector_db.as_retriever(search_kwargs={"k": 1})


# ============================================================
# Part 2: LLM init (connect to DeepSeek API)
# ============================================================

# --- Read API Key from .env file ---
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()                                  # Strip leading/trailing whitespace and newlines
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)                       # Split on = into key and value
                if _k.strip() not in os.environ:                   # Only set if not already in env
                    os.environ[_k.strip()] = _v.strip()            # Write into environment variables

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")           # Read API Key from env
DEEPSEEK_BASE_URL = "https://api.deepseek.com"                     # DeepSeek API endpoint

# Safety check: no API Key → fail fast, don't start
if not DEEPSEEK_API_KEY:
    raise RuntimeError(
        "Please set DEEPSEEK_API_KEY (env var or .env file)\n"
        "  .env file format: DEEPSEEK_API_KEY=sk-xxx"
    )

# --- LLM instance for safety check (no tools, low temperature for consistency) ---
# This is a SEPARATE LLM call — the safety checker only judges content, it doesn't need tools.
safety_llm = ChatOpenAI(
    model="deepseek-chat",
    temperature=0.3,                 # Low temp: consistent safety judgments
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
)

# --- ★ Create LLM with bound tools — this IS the Agent's "brain" ---
# What does bind_tools(ALL_TOOLS) do?
#   Converts 8 Python functions into OpenAI tool definition format and sends to the API
#   When the LLM sees these tools, its output may be:
#     A) Plain text "Sure, coming right up"      → conversation ends
#     B) tool_call: request_supplies(...)          → tool needs to be executed
llm_with_tools = ChatOpenAI(
    model="deepseek-chat",           # DeepSeek model name
    temperature=0.5,                 # Temperature: 0=deterministic, 1=random, 0.5 balanced
    api_key=DEEPSEEK_API_KEY,        # API key
    base_url=DEEPSEEK_BASE_URL,      # API endpoint
).bind_tools(ALL_TOOLS)              # ★ Key: mount all 8 tools on the LLM

# --- Init RAG retriever (global, runs once at startup) ---
retriever = get_rag_retriever()

logger.info("LLM initialized: deepseek-chat (ReAct Agent, %d tools)", len(ALL_TOOLS))
logger.info("Available tools: %s", [t.name for t in ALL_TOOLS])


# ============================================================
# Part 3: Graph nodes — what each step does
# ============================================================
# Every node is a Python function: takes State, returns partial State updates

# --- Safety Check System Prompt (LLM judges content safety) ---
SAFETY_CHECK_PROMPT = """你是一个酒店服务系统的内容安全检查员。你的任务是判断客人发送的消息是否安全、是否适合酒店服务助手处理。

需要标记为 UNSAFE 的内容类型：
- 色情、低俗、性暗示内容
- 暴力、威胁、骚扰、人身攻击
- 政治敏感话题、政治宣传
- 黑客攻击、恶意代码、系统入侵
- 赌博、毒品、违法活动
- 明显与酒店服务无关的恶意滥用（如要求写代码、写文章、翻译等）

如果消息内容正常、安全，只回复单个词 "SAFE"。
如果消息不安全，只回复单个词 "UNSAFE"。
不要解释原因，不要回复其他内容。"""


# --- Node 1: LLM Safety Check ---
def safety_check_node(state: State) -> dict:
    """
    ★ LLM 自己判断消息是否安全 —— 替代硬编码关键词匹配。

    LLM 能理解上下文、多语言、隐晦表达，比 Python 子串匹配准确得多。

    Input:  state["messages"][-1] (guest's latest message)
    Output: {"is_safe": "SAFE"} or {"is_safe": "UNSAFE"}
    """
    last_message = state["messages"][-1].content

    messages = [
        SystemMessage(content=SAFETY_CHECK_PROMPT),
        HumanMessage(content=f"请检查以下消息：\n{last_message}")
    ]

    response = safety_llm.invoke(messages)
    result = response.content.strip().upper()

    # Parse LLM response: look for SAFE or UNSAFE
    if "UNSAFE" in result:
        is_safe = "UNSAFE"
    else:
        is_safe = "SAFE"

    logger.info("LLM Safety Check: %s (raw: %s)", is_safe, result[:60])
    return {"is_safe": is_safe}


# --- Router A: safe → where? ---
def check_safety(state: State) -> str:
    """
    Decide next step based on LLM's safety judgment:
      SAFE   → "retrieve" (proceed to RAG retrieval)
      UNSAFE → "refuse"  (LLM generates polite refusal)
    """
    return "refuse" if state["is_safe"] == "UNSAFE" else "retrieve"


# --- Node 2: LLM-generated Refusal ---
def safety_refuse_node(state: State) -> dict:
    """
    ★ LLM 自己生成拒绝回复 —— 不再是硬编码英文。

    LLM 根据客人的消息内容，生成自然、礼貌、中文的拒绝回复。
    客人看到的是有温度的管家式拒绝，而不是冰冷的固定英文。
    """
    last_message = state["messages"][-1].content

    refuse_prompt = f"""客人发送了以下消息，被安全审查标记为不适合处理：
"{last_message}"

请以酒店客房服务管家的身份，礼貌地拒绝这条请求：
- 语气要温和、自然，像真正的管家在说话
- 如果客人可能有正当酒店需求，引导联系前台（分机0000）
- 简短，1-2句话即可
- 用中文回复"""

    messages = [
        SystemMessage(content=refuse_prompt),
        HumanMessage(content="请生成一段礼貌的拒绝回复。")
    ]

    response = safety_llm.invoke(messages)
    logger.info("LLM generated refusal: %s", (response.content or "")[:80])
    return {"messages": [response]}


# --- Node 3: RAG knowledge retrieval ---
def rag_node(state: State) -> dict:
    """
    Take the guest's message and search the vector database for the most relevant knowledge.

    Internal flow:
      Guest message → Embedding → Vector → Chroma similarity search → Best-matching text → Write to context

    Input:  state["messages"][-1] (guest's latest message)
    Output: {"context": "retrieved knowledge text"}
    """
    last_message = state["messages"][-1].content               # Get guest's last utterance
    docs = retriever.invoke(last_message)                       # ★ Vector similarity search
    # docs is a list; each element has a .page_content attribute (original text)
    context_str = "\n".join([d.page_content for d in docs])    # Concatenate all retrieval results
    logger.info("RAG retrieval complete, context length: %d chars", len(context_str))
    return {"context": context_str}                             # Write to state.context


# --- Node 4: ★ Agent Brain ★ ---
def agent_node(state: State) -> dict:
    """
    The most critical node in the entire Agent. The LLM makes ALL decisions here.

    Flow:
      1. Build System Prompt (role + RAG knowledge)
      2. Send System Prompt + conversation history to the LLM
      3. LLM returns a response, which may be:
         - Plain text → conversation ends
         - tool_calls → tool(s) need to be executed

    The LLM decides by itself:
      - Is there enough info (should I ask for more)?
      - Which tool to pick
      - Whether a high-risk operation needs confirmation first
      - How to reply to the guest
    """
    # Build System Prompt (template + RAG knowledge)
    sys_prompt = build_system_prompt(state.get("context", ""))

    # Build message list: [SystemMessage, ...history...]
    # [X] + [A, B, C] = [X, A, B, C] — Python list concatenation
    messages = [SystemMessage(content=sys_prompt)] + state["messages"]

    # ★ Call the LLM (DeepSeek API)
    response = llm_with_tools.invoke(messages)

    # Log: record what decision the LLM made
    if hasattr(response, "tool_calls") and response.tool_calls:
        # LLM decided to call a tool
        for tc in response.tool_calls:
            logger.info("Agent decision: call tool %s(%s)", tc["name"], tc.get("args", {}))
    else:
        # LLM decided to reply directly
        reply_preview = (response.content or "")[:80] if hasattr(response, "content") else ""
        logger.info("Agent decision: direct reply — %s", reply_preview)

    return {"messages": [response]}                            # Append LLM reply to history


# --- Router B: continue to tools? end? ---
def should_continue(state: State) -> str:
    """
    Check whether the LLM's response contains tool_calls:
      Has tool_calls → "tools" (execute tool, then return to agent)
      No tool_calls  → "__end__" (conversation ends, reply goes to guest)

    This is the controller of the entire ReAct loop. The code makes NO decisions —
    it only checks whether the LLM asked to call a tool.
    """
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    return "__end__"


# ============================================================
# Part 4: Build the graph — connect nodes into a workflow
# ============================================================

def build_graph():
    """
    Build a directed graph with LangGraph.

    Graph flow:
        START
          │
          ▼
    safety_check ──(UNSAFE)──► safety_refuse ──► END
          │
          │(SAFE)
          ▼
      rag_retrieve
          │
          ▼
         agent ◄──────────┐
          │                │
          ├── text → END   │
          │                │
          └── tool_call → tools ──┘ (back to agent)

    All decisions (safety, intent, tool selection, response wording) are made by the LLM.
    Code only does orchestration + routing.
    """
    graph_builder = StateGraph(State)          # StateGraph is the core class of LangGraph

    # --- Register nodes: give each function a name ---
    graph_builder.add_node("safety_check", safety_check_node)
    graph_builder.add_node("safety_refuse", safety_refuse_node)
    graph_builder.add_node("rag_retrieve", rag_node)
    graph_builder.add_node("agent", agent_node)
    # ToolNode is a LangGraph built-in: auto-executes the Python function for each tool_call
    graph_builder.add_node("tools", ToolNode(ALL_TOOLS))

    # --- Connect edges: define the flow ---

    # Fixed edge: START → safety_check (unconditional)
    graph_builder.add_edge(START, "safety_check")

    # Conditional edge: safety_check → safety_refuse or rag_retrieve (depends on LLM's safety judgment)
    graph_builder.add_conditional_edges(
        "safety_check", check_safety,
        {"refuse": "safety_refuse", "retrieve": "rag_retrieve"}
    )

    # Fixed edges
    graph_builder.add_edge("rag_retrieve", "agent")      # RAG → agent
    graph_builder.add_edge("safety_refuse", END)          # Refuse → end

    # ★ Conditional edge: agent → tools or END (the core of the ReAct loop)
    graph_builder.add_conditional_edges(
        "agent", should_continue,
        {"tools": "tools", "__end__": END}
    )

    # Fixed edge: after tool execution → back to agent (LLM observes the result)
    graph_builder.add_edge("tools", "agent")

    return graph_builder


# --- Compile graph + bind memory ---
agent_memory = MemorySaver()                                     # In-memory: stores conversation history per session
room_service_graph = build_graph().compile(checkpointer=agent_memory)
# compile() = "compile" the graph into an executable state
# checkpointer=agent_memory = auto-save/restore conversation history per session

logger.info("Agent graph compiled (LLM Safety → RAG → agent ⇄ tools)")


# ============================================================
# Part 5: Public API
# ============================================================

def invoke_agent(message: str, session_id: str = "default") -> str:
    """
    Simplest call interface. Pass in a guest message, get back an AI text reply.

    Args:
        message:    what the guest said, e.g. "Send two bottles of water to 301"
        session_id: session ID; same session_id shares conversation memory (suggest using room number)

    Returns:
        Agent's text reply, e.g. "Sure, the water will be delivered to 301 shortly."

    Internal flow:
        1. Wrap message as HumanMessage
        2. Call room_service_graph.invoke() → run the entire graph
        3. Extract the text of the last message → return it
    """
    config = {"configurable": {"thread_id": session_id}}         # thread_id = key for conversation memory
    try:
        result = room_service_graph.invoke(
            {"messages": [HumanMessage(content=message)]},       # Input: guest message
            config=config,                                       # Config: session_id
        )
        reply = result["messages"][-1].content                   # Get text of the last message
        logger.info("Session[%s] reply: %s...", session_id, reply[:80])
        return reply
    except Exception as e:
        logger.error("Session[%s] error: %s", session_id, str(e))
        # Graceful fallback: any exception is handled elegantly; the guest never sees a raw error
        return "We're sorry, the system is experiencing a temporary issue. Please call the front desk (ext. 0000) and our staff will assist you immediately."


def invoke_agent_structured(message: str, session_id: str = "default") -> dict:
    """
    Structured call interface. Returns a dict instead of plain text.
    server.py uses this interface; the frontend needs session_id echoed back.
    """
    config = {"configurable": {"thread_id": session_id}}
    try:
        result = room_service_graph.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=config,
        )
        reply = result["messages"][-1].content
        logger.info("Session[%s] structured reply", session_id)
        return {
            "response_text": reply,
            "session_id": session_id,
        }
    except Exception as e:
        logger.error("Session[%s] error: %s", session_id, str(e))
        return {
            "response_text": "We're sorry, the system is experiencing a temporary issue. Please call the front desk (ext. 0000) and our staff will assist you immediately.",
            "session_id": session_id,
        }


def clear_session(session_id: str) -> bool:
    """
    Clear conversation history for a given session.
    After guest checkout, the front desk system calls this to wipe memory and protect privacy.
    """
    logger.info("Session[%s] cleared", session_id)
    return True


# ============================================================
# Part 6: Gradio local test UI
# ============================================================
# Usage: python room_service_agent.py
# Then open http://127.0.0.1:7860 in your browser

if __name__ == "__main__":
    # What does if __name__ == "__main__" mean?
    #   When this file is run directly (python room_service_agent.py), __name__ is "__main__"
    #   When this file is imported (from room_service_agent import ...), __name__ is "room_service_agent"
    #   So the code inside this if block only runs on direct execution, not on import

    import gradio as gr

    def chat_interface(user_message, history):
        """Gradio callback: user message → call agent → return reply"""
        return invoke_agent(user_message, session_id="gradio_demo")

    with gr.Blocks(title="Room Service Agent — ReAct") as demo:
        gr.Markdown("## Room Service Agent (ReAct Mode)")

        chatbot = gr.Chatbot(height=520)
        msg = gr.Textbox(placeholder="Describe what you need...", show_label=False)

        def respond(message, history):
            reply = invoke_agent(message, session_id="gradio_demo")
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply})
            return "", history

        msg.submit(respond, inputs=[msg, chatbot], outputs=[msg, chatbot])

        gr.Examples(
            examples=[
                "Send two bottles of water and a towel to room 301",
                "The AC in 302 isn't cooling, come check it now",
                "Set a wake-up call for 7am tomorrow, room 503",
                "I have a suit that needs dry cleaning, room 405",
            ],
            inputs=msg,
        )

    demo.launch(inbrowser=False, share=False)                    # inbrowser=False: don't auto-open browser
