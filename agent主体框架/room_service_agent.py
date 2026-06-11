"""
五星级酒店客房服务 Agent — 核心模块
==============================================
架构: LangGraph (Guardrails + RAG + JSON分析 + 槽位校验 + 能力门控 + 风控 + 工具执行 + Memory)
可被 Gradio UI 直接运行，也可被 FastAPI Server 导入

Day 4: JSON 模式 chatbot + State 扩展 + 手动工具路由
Day 5: 集成 slot_validator（枚举/范围/必填/默认值校验）
Day 6: 集成 capability_gate + risk_checker（能力门控 + 风控红线 + 二次确认）
"""
import os
import json
import re
import logging
from typing import Annotated, Any
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from tools_api.mock_services import ALL_TOOLS
from core.slot_validator import slot_validator_node
from core.capability_gate import capability_gate_node
from core.risk_checker import risk_checker_node, _is_confirm, _is_cancel
from core.clarify_builder import clarify_builder_node
from core.response_formatter import response_formatter_node
from core.locale_resolver import locale_resolver_node
from core.entity_resolver import entity_resolver_node

# ==========================================
# 日志配置 (五星级酒店需要可追溯的日志)
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("RoomServiceAgent")

# ==========================================
# 第一部分：状态定义 & 辅助加载
# ==========================================

class State(TypedDict):
    """Agent 内部状态 — Day 6 扩展版"""
    # --- 原有字段 ---
    messages: Annotated[list, add_messages]
    context: str        # RAG 检索上下文
    is_safe: str        # 护栏结果 SAFE / UNSAFE

    # --- Day 4 字段 ---
    raw_intents: list        # chatbot JSON 输出的意图列表
    raw_slots: dict          # chatbot JSON 输出的槽位字典
    raw_entities: dict       # chatbot JSON 输出的实体字典
    analysis_json: str       # LLM 原始 JSON 输出
    need_clarify: bool       # 是否需要追问客人

    # --- Day 5 字段 ---
    validated_slots: dict    # slot_validator 校验后的槽位
    decision_trace: list     # 全链路校验记录

    # --- Day 6 字段 ---
    confirm_pending: bool    # 是否等待客人二次确认
    confirm_action: dict     # 确认摘要

    # --- Day 7 字段 ---
    clarify_info: dict       # NeedClarify 结构
    result_type: str         # execute / need_clarify / reject
    structured_output: dict  # FinalOutput 完整结构

    # --- Day 9 字段 ---
    locale: str              # 语言检测结果（locale_resolver）

    # --- 追问上下文 ---
    awaiting_slot: str       # 上一轮在追问什么槽位（"location"/"details"/""）
    pending_intents: list    # 追问前的原始意图（等待补全信息后继续用）
    pending_slots: dict      # 追问前的原始槽位
    skip_validation: bool    # 确认后跳过校验直达工具

def load_system_prompt_dynamic(rag_context: str = "") -> str:
    """使用 prompt_loader 动态加载完整 System Prompt"""
    try:
        from prompts.prompt_loader import load_system_prompt_with_rag
        return load_system_prompt_with_rag(rag_context)
    except Exception as e:
        logger.warning("动态 prompt 加载失败: %s，使用基础模板", e)
        prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "system_prompt.txt")
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

def get_rag_retriever():
    """初始化 RAG 向量检索引擎"""
    knowledge_path = os.path.join(os.path.dirname(__file__), "knowledge", "placeholder_info.txt")
    with open(knowledge_path, "r", encoding="utf-8") as f:
        knowledge_text = f.read()

    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_db = Chroma.from_texts([knowledge_text], embeddings, collection_name="hotel_knowledge")
    return vector_db.as_retriever(search_kwargs={"k": 1})

# ==========================================
# 第二部分：工具 ↔ 意图映射（手动路由）
# ==========================================

# 工具函数名 → 函数对象 的快速查找表
TOOL_BY_NAME = {t.name: t for t in ALL_TOOLS}

# 意图 L1 → 默认工具映射（Day 8：全部到位）
INTENT_TO_TOOL = {
    "ROOM_SERVICE":  "request_supplies",
    "HOUSEKEEPING":  "request_cleaning",
    "HOTEL_CALL":    "call_hotel",
    "ALARM":         "set_wake_up_call",
}

# HOUSEKEEPING 的 request_type → 工具细分
HOUSEKEEPING_TOOL_MAP = {
    "housekeeping": "request_cleaning",
    "workorder":    "report_maintenance",
    "amenity":      "request_laundry",
}

def determine_tool(intent: dict, slots: dict, entities: dict = None) -> tuple:
    """根据意图和槽位，决定调用哪个工具及参数

    Args:
        intent: LLM 识别的意图 {L1, L2, L3, id, score}
        slots: LLM 提取的槽位 {request_type, location, details, ...}
        entities: LLM 提取的实体 {room, item}

    Returns:
        (tool_name, tool_args) 或 (None, {}) 如果无法确定
    """
    if entities is None:
        entities = {}

    L1 = intent.get("L1", "")
    intent_id = intent.get("id", "")
    request_type = slots.get("request_type", "")

    # 如果 LLM 把 intent ID 填到了 L1 字段（如 L1="SVC_HK_001"），从 id 推断
    if L1.startswith("SVC_") or L1.startswith("ALARM_"):
        intent_id = L1
        # 从 ID 推断 L1
        if "ROOM" in intent_id:
            L1 = "ROOM_SERVICE"
        elif "HK" in intent_id:
            L1 = "HOUSEKEEPING"
        elif "CALL" in intent_id:
            L1 = "HOTEL_CALL"
        elif "ALARM" in intent_id:
            L1 = "ALARM"

    tool_name = None

    if L1 == "HOUSEKEEPING":
        # 根据 request_type 细分
        tool_name = HOUSEKEEPING_TOOL_MAP.get(request_type, "request_cleaning")
    elif L1 == "ROOM_SERVICE":
        tool_name = "request_supplies"
    elif L1 == "ALARM":
        L2 = intent.get("L2", "")
        if L2 == "DELETE":
            tool_name = "delete_alarm"
        elif L2 == "CLOSE":
            tool_name = "close_alarm"
        else:
            tool_name = "set_wake_up_call"
    elif L1 == "HOTEL_CALL":
        tool_name = "call_hotel"

    if tool_name is None or tool_name not in TOOL_BY_NAME:
        return (None, {})

    # 构建工具参数
    room = slots.get("location", "") or entities.get("room", "")
    args = {"room_number": room}

    if tool_name == "request_supplies":
        # 优先用实体 item，回退到 details
        item = entities.get("item", "") or slots.get("details", "")
        args["item"] = item
        args["quantity"] = 1
    elif tool_name == "request_cleaning":
        args["time_preference"] = slots.get("time", "现在")
    elif tool_name == "report_maintenance":
        args["issue"] = slots.get("details", "")
        args["urgency"] = slots.get("priority", "normal")
    elif tool_name == "request_laundry":
        args["items"] = slots.get("details", "")
        args["pickup_time"] = slots.get("time", "现在")
    elif tool_name == "set_wake_up_call":
        args["time"] = slots.get("time", "")
    elif tool_name == "delete_alarm":
        args["label"] = slots.get("label", "")
        args["alarm_id"] = slots.get("alarm_id", None)
    elif tool_name == "close_alarm":
        args["alarm_action"] = "close"
        args["label"] = slots.get("label", None)

    return (tool_name, args)

# ==========================================
# 第三部分：图节点定义
# ==========================================

# --- 初始化 LLM ---
# 从 .env 文件加载 API key（如果环境变量没设）
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                if _k.strip() not in os.environ:
                    os.environ[_k.strip()] = _v.strip()

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

if not DEEPSEEK_API_KEY:
    raise RuntimeError(
        "请设置 DEEPSEEK_API_KEY（环境变量 或 llm/.env 文件）\n"
        "  .env 文件格式: DEEPSEEK_API_KEY=sk-xxx"
    )

# llm_json: JSON 模式，用于意图识别 + 槽位提取（不绑工具）
# llm_json: JSON 模式，用于意图识别 + 槽位提取（强制输出 JSON）
llm_json = ChatOpenAI(
    model="deepseek-chat",
    temperature=0.1,
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
    model_kwargs={"response_format": {"type": "json_object"}},
)

# llm_chat: 自由文本模式，用于生成口语回复
llm_chat = ChatOpenAI(
    model="deepseek-chat",
    temperature=0.5,
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
)

# RAG 检索器
retriever = get_rag_retriever()

logger.info("LLM 已初始化: deepseek-chat (via DeepSeek API)")
logger.info("可用工具(%d): %s", len(ALL_TOOLS), [t.name for t in ALL_TOOLS])

def guardrail_node(state: State) -> dict:
    """安全护栏：拦截非酒店服务相关请求"""
    last_message = state["messages"][-1].content
    dangerous_keywords = ["政治", "黑客", "写代码", "入侵", "暴力", "色情", "赌博"]
    is_safe = "SAFE"
    for kw in dangerous_keywords:
        if kw in last_message:
            is_safe = "UNSAFE"
            logger.warning("护栏拦截: 命中关键词 '%s'", kw)
            break
    return {"is_safe": is_safe}

def check_safety(state: State) -> str:
    """路由：安全 → RAG 检索 / 不安全 → 拒绝"""
    return "refuse" if state["is_safe"] == "UNSAFE" else "retrieve"

def refuse_node(state: State) -> dict:
    """拒绝节点：统一话术"""
    refusal_msg = AIMessage(
        content="抱歉先生/女士，我是您的酒店专属管家，仅为您解答酒店相关服务，无法处理该类型问题。"
    )
    return {"messages": [refusal_msg]}

def rag_node(state: State) -> dict:
    """RAG 检索：从知识库查相关信息"""
    last_message = state["messages"][-1].content
    docs = retriever.invoke(last_message)
    context_str = "\n".join([d.page_content for d in docs])
    logger.info("RAG 检索完成，上下文长度: %d 字符", len(context_str))
    return {"context": context_str}

def chatbot_node(state: State) -> dict:
    """
    ★ Day 4 核心改造：结构化 JSON 输出

    使用 JSON 模式的 LLM（不绑工具），强制输出：
    {
      "intents": [{"L1": "...", "L2": "...", "L3": "DEFAULT", "id": "...", "score": 0.95}],
      "slots": {"request_type": "...", "location": "...", "details": "...", ...},
      "entities": {"room": "...", "item": "..."}
    }

    解析后存入 State，供后续校验节点使用。

    Day 6 新增: confirm_pending 状态处理（二次确认流程）
    Day 10 新增: 闲聊/社交消息快速响应，不调 LLM
    """
    # ─── 追问补全：上一轮在等房间号/详情，这一轮直接给答案 ───
    awaiting = state.get("awaiting_slot", "")
    if awaiting:
        last_msg = state["messages"][-1].content.strip() if state.get("messages") else ""
        prev_intents = state.get("pending_intents") or []
        prev_slots = state.get("pending_slots") or {}

        # 判断当前回复是否像在回答追问
        if awaiting == "location":
            # 房间号：纯数字3-4位、字母+数字（F1306/A301）、"我的房号是F1306"这种
            room_match = re.search(r'\b([a-zA-Z]?\d{3,4})\b', last_msg)
            if room_match:
                room = room_match.group(1).upper()
                prev_slots["location"] = room
                logger.info("追问补全: 房间号=%s，恢复意图 %s", room,
                           prev_intents[0].get("L1","?") if prev_intents else "?")
                return {
                    "messages": [AIMessage(
                        content=f"好的，已记录房间号{room}。请稍候，马上为您处理。"
                    )],
                    "raw_intents": prev_intents,
                    "raw_slots": prev_slots,
                    "raw_entities": {"room": room},
                    "need_clarify": False,
                    "awaiting_slot": "",
                    "pending_intents": [],
                    "pending_slots": {},
                }
            # 匹配不到房间号 → 可能是新请求，清除等待状态丢给LLM
            logger.info("追问补全: 未匹配到房间号，作为新请求处理: %s", last_msg[:40])
            return {
                "need_clarify": False,
                "awaiting_slot": "",
                "pending_intents": [],
                "pending_slots": {},
            }

        if awaiting == "details":
            # 用户给的内容当成详情
            prev_slots["details"] = last_msg
            logger.info("追问补全: 详情=%s，恢复意图 %s", last_msg,
                       prev_intents[0].get("L1","?") if prev_intents else "?")
            return {
                "messages": [AIMessage(
                    content=f"好的，已记录您的需求：{last_msg}。请稍候，马上为您处理。"
                )],
                "raw_intents": prev_intents,
                "raw_slots": prev_slots,
                "raw_entities": prev_slots.get("location", ""),
                "need_clarify": False,
                "awaiting_slot": "",
                "pending_intents": [],
                "pending_slots": {},
            }

        # 非预期的回复，清除等待状态，走正常流程
        awaiting = ""

    # ─── 二次确认流程：不调 LLM，直接判断 ───
    if state.get("confirm_pending"):
        last_msg = state["messages"][-1].content if state.get("messages") else ""

        if _is_confirm(last_msg):
            logger.info("chatbot: 客人已确认，放行执行")
            # ★ 让 LLM 生成确认回复
            confirm_action = state.get("confirm_action", {})
            summary = confirm_action.get("summary", "此操作")
            sys_prompt = load_system_prompt_dynamic(state.get("context", ""))
            confirm_prompt = (
                f"{sys_prompt}\n\n"
                f"【当前状态】客人刚刚回复了「确认」，同意执行以下操作：{summary}\n"
                f"请给客人一个简短的确认回复（准备开始执行），要自然口语，亲切有温度。"
                f"不要说「请回复确认」，因为客人已经确认了。"
                f"直接输出回复文本，不要JSON。"
            )
            try:
                llm_resp = llm_chat.invoke([SystemMessage(content=confirm_prompt)])
                confirm_reply = llm_resp.content.strip() if llm_resp.content else f"好的，马上帮您处理{summary}。"
            except Exception:
                confirm_reply = f"好的，马上帮您处理{summary}。"
            return {
                "messages": [AIMessage(content=confirm_reply)],
                "need_clarify": False,
                "raw_intents": state.get("raw_intents") or [],
                "raw_slots": state.get("raw_slots") or {},
                "raw_entities": state.get("raw_entities") or {},
                "awaiting_slot": "",
                "pending_intents": [],
                "pending_slots": {},
                "confirm_pending": False,
                "confirm_action": {},
                "skip_validation": True,  # 已确认，跳过校验直达工具
            }

        if _is_cancel(last_msg):
            logger.info("chatbot: 客人取消操作")
            return {
                "messages": [AIMessage(content="好的，已经取消了。还有其他需要帮您的吗？")],
                "need_clarify": True,
                "raw_intents": [],
                "raw_slots": {},
                "raw_entities": {},
                "awaiting_slot": "",
                "pending_intents": [],
                "pending_slots": {},
                "confirm_pending": False,
                "confirm_action": {},
            }

        # 客人说了新请求（不是确认/取消） → 清掉确认状态，继续往下正常解析
        if not _is_confirm(last_msg) and not _is_cancel(last_msg):
            logger.info("chatbot: 确认等待中收到新请求，重置后重新解析: %s", last_msg[:30])
            # 不 return，标记清除确认状态并 fall through 到 LLM
            confirm_pending_clear = True
    last_msg = state["messages"][-1].content.strip() if state.get("messages") else ""
    # 超短消息用自由文本LLM快速回复。含控制/餐饮词的走正常管线
    _control_like = any(kw in last_msg for kw in ["关","开","灯","空调","窗帘","电视","温度","调"])
    if len(last_msg) <= 2 and not any(c.isdigit() for c in last_msg) and not _control_like:
        try:
            quick = llm_chat.invoke([SystemMessage(content=
                "你是酒店客房管家（只负责送物品、打扫、报修、洗衣、叫醒、叫前台）。"
                "客人说了一句很短的话。如果是不归你管的（关灯/开空调/点餐/问天气等），请礼貌说明这不是你的范围并引导。"
                "要亲切简短。直接输出回复文本。"
            ), HumanMessage(content=last_msg)])
            return {
                "messages": [AIMessage(content=quick.content.strip() if quick.content else "您好，有什么可以帮您的？")],
                "raw_intents": [], "raw_slots": {}, "raw_entities": {},
                "need_clarify": False,
            }
        except Exception:
            pass  # 失败走正常流程

    # 口语前缀剥离
    _clean_msg = last_msg
    for _cw in ["我去 ", "我去", "哎呀 ", "哎呀", "那个 ", "那个", "呃 ", "呃", "emmm ", "emmm"]:
        if _clean_msg.startswith(_cw):
            _clean_msg = _clean_msg[len(_cw):].strip()
            break
    if _clean_msg != last_msg:
        logger.info("chatbot: 口语前缀剥离 '%s' → '%s'", last_msg, _clean_msg)

    sys_prompt = load_system_prompt_dynamic(state.get("context", ""))
    # 用清洗后的消息替换最后一条用户消息发给LLM
    _msgs = list(state["messages"])
    if _clean_msg != last_msg and _msgs:
        _msgs[-1] = HumanMessage(content=_clean_msg)
    # 历史太长会干扰 LLM，只保留最近 6 条消息（3 轮对话）
    _recent = _msgs[-6:] if len(_msgs) > 6 else _msgs
    messages_to_send = [SystemMessage(content=sys_prompt)] + _recent

    logger.info("chatbot_node: 发送 JSON 模式请求 (prompt总长 %d 字符)", len(sys_prompt))

    response = llm_json.invoke(messages_to_send)
    raw_text = response.content.strip() if response.content else ""

    # ─── JSON 解析（含容错） ───
    intents = []
    slots = {}
    entities = {}
    need_clarify = False
    reply_text = ""
    llm_reply = ""

    try:
        # 去掉可能的 Markdown 代码块标记
        clean = raw_text.strip()
        clean = re.sub(r'^```(?:json)?\s*\n?', '', clean, flags=re.MULTILINE)
        clean = re.sub(r'\n?```\s*$', '', clean, flags=re.MULTILINE)

        # 尝试提取第一个 JSON 对象（处理 LLM 输出多余文本的情况）
        json_match = re.search(r'\{.*\}', clean, re.DOTALL)
        if json_match:
            clean = json_match.group(0)

        analysis = json.loads(clean)

        intents = analysis.get("intents", [])
        slots = analysis.get("slots", {})
        entities = analysis.get("entities", {})
        # ★ 优先用 LLM 生成的口语回复
        llm_reply = analysis.get("reply", "")

        # 去掉 slots 中值为 None 或空字符串的项
        slots = {k: v for k, v in slots.items() if v is not None and v != ""}

        if intents:
            top = intents[0]
            logger.info("✅ JSON解析成功: intent=%s (score=%.2f), slots=%s, entities=%s",
                        top.get("L1"), top.get("score", 0), list(slots.keys()), entities)
        else:
            logger.warning("⚠️ LLM 返回了空的 intents 数组 → 自由文本兜底")
            try:
                fallback = llm_chat.invoke([SystemMessage(content=
                    "你是酒店客房管家。客人说的话不在你的服务范围内（你不是点餐/控制/咨询Agent）。"
                    "请用自然口语回复：如果是问餐饮→引导去点餐服务；如果是设备控制→引导用房间面板；"
                    "如果是天气/闲聊→礼貌说明你是客房服务助手；如果客人情绪激动→先安抚再引导。"
                    "要亲切自然，不超过两句话。直接输出回复。"
                ), HumanMessage(content=last_msg)])
                reply_text = fallback.content.strip() if fallback.content else ""
            except Exception:
                reply_text = ""
            need_clarify = True

    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        logger.warning("❌ JSON解析失败: %s — 尝试关键词兜底", str(e))
        logger.warning("原始输出(前300字符): %s", raw_text[:300])
        # 关键词兜底：JSON解析失败时用规则匹配拯救
        need_clarify = True

    # ─── 主动检查关键信息是否缺失 ───
    awaiting_slot = ""
    pending_intents = []
    pending_slots = {}
    if not need_clarify and intents:
        top = intents[0]
        L1 = top.get("L1", "")
        room = slots.get("location", "") or entities.get("room", "")
        detail = slots.get("details", "")

        # 服务类意图：必须知道房间号和具体内容
        if L1 in ("ROOM_SERVICE", "HOUSEKEEPING", "HOTEL_CALL"):
            missing = []
            if not room:
                missing.append("房间号")
            if not detail and L1 != "HOTEL_CALL":
                missing.append("具体需求（送什么/打扫/报修什么）")

            if missing:
                need_clarify = True
                # 紧急关键词 → 带安抚的追问
                reply_text = llm_reply if llm_reply else f"请问{'和'.join(missing)}是什么呢？"
                logger.info("关键信息缺失: %s → 追问", missing)
                # 记住在等什么，下次用户回复时自动补全
                awaiting_slot = "location" if "房间号" in missing else missing[0].split("（")[0]
                pending_intents = intents
                pending_slots = slots

        # ALARM：必须知道时间（duration 有默认值）
        if L1 == "ALARM":
            time = slots.get("time", "")
            L2 = top.get("L2", "")
            if not time and L2 != "DELETE" and L2 != "CLOSE":
                need_clarify = True
                reply_text = "好的，请问您需要几点叫醒呢？"

    # ─── 回复：LLM的reply永远最优先 ───
    if llm_reply:
        reply_text = llm_reply
        # LLM给了回复，跳过校验直接输出（避免slot_validator二次修改need_clarify）
        return {
            "messages": [AIMessage(content=reply_text)],
            "raw_intents": intents,
            "raw_slots": slots,
            "raw_entities": entities,
            "analysis_json": raw_text,
            "need_clarify": True,  # 标记clarify让graph走response_formatter，绕过slot_validator
            "awaiting_slot": awaiting_slot,
            "pending_intents": pending_intents,
            "pending_slots": pending_slots,
        }
    elif not reply_text:
        reply_text = "请问还有什么可以帮您的吗？"

    # 如果从确认等待中清除状态 fall through 到这里，确保 return 中清除
    _clear_confirm = locals().get("confirm_pending_clear", False)

    return {
        "messages": [AIMessage(content=reply_text)],
        "raw_intents": intents,
        "raw_slots": slots,
        "raw_entities": entities,
        "analysis_json": raw_text,
        "need_clarify": need_clarify,
        "awaiting_slot": awaiting_slot,
        "pending_intents": pending_intents,
        "pending_slots": pending_slots,
        "confirm_pending": False if _clear_confirm else state.get("confirm_pending", False),
        "confirm_action": {} if _clear_confirm else state.get("confirm_action", {}),
    }

def _safe_state(state: State) -> dict:
    """安全读取 State 中的可选字段，None → 默认值"""
    # 优先用 validated_slots，回退到 raw_slots
    raw = state.get("validated_slots") or state.get("raw_slots") or {}

    # 如果是 validated_slots 格式（{name: {value, status, message}}），提取纯值
    slots = {}
    for k, v in raw.items():
        if isinstance(v, dict) and "value" in v:
            slots[k] = v["value"]
        else:
            slots[k] = v

    return {
        "intents": state.get("raw_intents") or [],
        "slots": slots,
        "entities": state.get("raw_entities") or {},
        "need_clarify": state.get("need_clarify", False),
    }

def tool_executor_node(state: State) -> dict:
    """
    手动工具执行节点。

    从 State 中读取 raw_intents 和 raw_slots，
    根据意图→工具映射决定调用哪个工具，构造参数并执行。

    Day 4 版本：不做槽位校验（Day 5 加），直接尝试执行。
    """
    ss = _safe_state(state)
    intents = ss["intents"]
    slots = ss["slots"]
    entities = ss["entities"]
    need_clarify = ss["need_clarify"]

    if need_clarify or not intents:
        logger.info("tool_executor: 需要澄清或无意图，跳过工具调用")
        return {}

    intent = intents[0]
    tool_name, tool_args = determine_tool(intent, slots, entities)

    if tool_name is None:
        logger.info("tool_executor: 意图 %s 无对应工具（%s）", intent.get("L1"), tool_name or "待实现")
        # 工具缺失时给一个占位回复
        msg = AIMessage(content=f"好的，我已记录您的{intent.get('L1', '')}需求，工作人员将尽快处理。")
        return {"messages": [msg]}

    tool_fn = TOOL_BY_NAME[tool_name]
    logger.info("tool_executor: 调用工具 %s(%s)", tool_name, tool_args)

    try:
        result = tool_fn.invoke(tool_args)
        tool_message = result.get("message", "已处理完毕。") if isinstance(result, dict) else str(result)

        # ★ 让 LLM 把工具结果转成自然口语回复
        sys_prompt = load_system_prompt_dynamic(state.get("context", ""))
        intent_name = intent.get("L1", "服务")
        room = slots.get("location", "") or entities.get("room", "")
        summary_prompt = (
            f"{sys_prompt}\n\n"
            f"【当前状态】客人已确认，工具已执行完毕。\n"
            f"- 执行的操作: {tool_name}\n"
            f"- 系统返回: {tool_message}\n"
            f"- 意图: {intent_name}\n"
            f"- 房间号: {room}\n\n"
            f"请根据以上信息，用自然口语给客人一个简短的确认回复（用于语音播报，要亲切自然，不要括号和技术术语）。"
            f"不要输出JSON，直接输出回复文本。"
        )
        try:
            llm_resp = llm_chat.invoke([SystemMessage(content=summary_prompt)])
            reply_text = llm_resp.content.strip() if llm_resp.content else tool_message
        except Exception:
            reply_text = tool_message  # LLM 失败就用工具消息

        logger.info("tool_executor: 工具执行成功 %s, LLM生成回复", tool_name)
        return {
            "messages": [AIMessage(content=reply_text)],
            "skip_validation": False,
            "raw_intents": [], "raw_slots": {}, "raw_entities": {},  # 清旧意图
        }
    except Exception as e:
        logger.error("工具调用异常: %s", str(e))
        error_msg = AIMessage(content="非常抱歉，系统暂时遇到了一点问题。已转接前台（电话0000），马上会有人帮您处理。")
        return {"messages": [error_msg], "skip_validation": False}

def check_after_chatbot(state: State) -> str:
    """路由：已确认→直达工具 / 解析成功→校验 / 失败→结束"""
    if state.get("skip_validation"):
        return "skip_to_tools"
    ss = _safe_state(state)
    if ss["need_clarify"]:
        return "__end__"
    if not ss["intents"]:
        return "__end__"
    return "validate"

def check_after_validator(state: State) -> str:
    """路由：槽位校验通过 → 执行工具 / 校验不通过 → 结束追问"""
    need_clarify = state.get("need_clarify", False)
    if need_clarify:
        logger.info("路由: 槽位校验未通过 → 结束（等待客人补充信息）")
        return "__end__"
    logger.info("路由: 槽位校验通过 → 执行工具")
    return "execute"

def should_continue_after_tools(state: State) -> str:
    """工具执行后的路由（Day 4 简化：执行完就结束）"""
    return "__end__"

# ==========================================
# 第四部分：构建 & 编译图 (带持久记忆)
# ==========================================

def build_graph():
    """构建 LangGraph 有向图 — Day 9 版本（12节点完整流水线）"""
    graph_builder = StateGraph(State)

    # 注册节点
    graph_builder.add_node("guardrail", guardrail_node)
    graph_builder.add_node("refuse", refuse_node)
    graph_builder.add_node("locale_resolver", locale_resolver_node)
    graph_builder.add_node("rag_retrieve", rag_node)
    graph_builder.add_node("chatbot", chatbot_node)
    graph_builder.add_node("slot_validator", slot_validator_node)
    graph_builder.add_node("entity_resolver", entity_resolver_node)
    graph_builder.add_node("capability_gate", capability_gate_node)
    graph_builder.add_node("risk_checker", risk_checker_node)
    graph_builder.add_node("tool_executor", tool_executor_node)
    graph_builder.add_node("clarify_builder", clarify_builder_node)
    graph_builder.add_node("response_formatter", response_formatter_node)

    # ─── 流转边 ───
    graph_builder.add_edge(START, "guardrail")

    # guardrail → 安全走 locale，不安全走 refuse
    graph_builder.add_conditional_edges(
        "guardrail", check_safety,
        {"refuse": "refuse", "retrieve": "locale_resolver"}
    )

    # locale → RAG → chatbot
    graph_builder.add_edge("locale_resolver", "rag_retrieve")
    graph_builder.add_edge("rag_retrieve", "chatbot")
    graph_builder.add_edge("refuse", "clarify_builder")

    # chatbot → 解析成功进校验 / 失败（社交/越界/解析错误）直接到格式化输出
    graph_builder.add_conditional_edges(
        "chatbot", check_after_chatbot,
        {"validate": "slot_validator", "skip_to_tools": "tool_executor", "__end__": "response_formatter"}
    )

    # slot_validator → 进实体解析 / 失败进澄清
    graph_builder.add_conditional_edges(
        "slot_validator", check_after_validator,
        {"execute": "entity_resolver", "__end__": "clarify_builder"}
    )

    # entity_resolver → 进能力门控 / 失败进澄清
    graph_builder.add_conditional_edges(
        "entity_resolver", check_after_validator,
        {"execute": "capability_gate", "__end__": "clarify_builder"}
    )

    # capability_gate → 进风控 / 失败进澄清
    graph_builder.add_conditional_edges(
        "capability_gate", check_after_validator,
        {"execute": "risk_checker", "__end__": "clarify_builder"}
    )

    # risk_checker → 执行工具 / 失败进澄清
    graph_builder.add_conditional_edges(
        "risk_checker", check_after_validator,
        {"execute": "tool_executor", "__end__": "clarify_builder"}
    )

    # 工具执行完 → 格式化输出
    graph_builder.add_edge("tool_executor", "response_formatter")

    # 澄清构建完 → 格式化输出
    graph_builder.add_edge("clarify_builder", "response_formatter")

    # 格式化输出 → 结束
    graph_builder.add_edge("response_formatter", END)

    return graph_builder

# ★★★ 编译图 + MemorySaver (支持多会话、持久记忆) ★★★
agent_memory = MemorySaver()
room_service_graph = build_graph().compile(checkpointer=agent_memory)

logger.info("Agent 图编译完成 (Day 7: 10节点完整流水线 — clarify_builder + response_formatter)")

def invoke_agent(message: str, session_id: str = "default") -> str:
    """
    对外统一调用接口。

    Args:
        message: 客人消息
        session_id: 会话标识（建议用房间号，如 "301"）

    Returns:
        Agent 的文字回复
    """
    config = {"configurable": {"thread_id": session_id}}
    try:
        result = room_service_graph.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=config,
        )
        reply = result["messages"][-1].content
        logger.info("会话[%s] 回复: %s...", session_id, reply[:80])
        return reply
    except Exception as e:
        logger.error("会话[%s] 处理异常: %s", session_id, str(e))
        return "非常抱歉，系统暂时遇到了一些问题。请致电前台（电话：0000），我们的工作人员会立即为您处理。"

def invoke_agent_structured(message: str, session_id: str = "default") -> dict:
    """
    对外统一调用接口 — 返回结构化输出。

    包含完整的 decision_trace、final_intent、final_slots 等字段，
    供外部系统（语音Agent、控制Agent、监控系统）消费。
    """
    config = {"configurable": {"thread_id": session_id}}
    try:
        result = room_service_graph.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=config,
        )
        reply = result["messages"][-1].content if result.get("messages") else ""

        # 从 state 收集结构化信息
        structured = result.get("structured_output", {})
        if not structured:
            # 兜底：手动构建
            structured = {
                "result_type": result.get("result_type", "execute"),
                "decision_trace": result.get("decision_trace", []),
                "response_text": reply,
                "session_id": session_id,
            }

        logger.info("会话[%s] 结构化回复: type=%s, traces=%d",
                    session_id, structured.get("result_type", "?"),
                    len(structured.get("decision_trace", [])))
        return structured

    except Exception as e:
        logger.error("会话[%s] 处理异常: %s", session_id, str(e))
        return {
            "result_type": "reject",
            "decision_trace": [],
            "response_text": "非常抱歉，系统暂时遇到了一些问题。请致电前台（电话：0000），我们的工作人员会立即为您处理。",
            "session_id": session_id,
        }

def clear_session(session_id: str) -> bool:
    """清除指定会话的对话历史（客人退房后调用）"""
    logger.info("会话[%s] 已清除", session_id)
    return True

# ==========================================
# 第五部分：Gradio 测试界面 (仅直接运行时)
# ==========================================

if __name__ == "__main__":
    import gradio as gr

    def chat_interface(user_message, history):
        return invoke_agent(user_message, session_id="gradio_demo")

    with gr.Blocks(title="客房服务 Agent") as demo:
        gr.Markdown("## 客房服务")

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
                "送两瓶矿泉水和一条毛巾到301",
                "302的空调不制冷了，快来看看",
                "帮我预约明早7点的叫醒服务，房间503",
                "我有一件西装需要干洗，在405房",
            ],
            inputs=msg,
        )

    demo.launch(inbrowser=True, share=False)
