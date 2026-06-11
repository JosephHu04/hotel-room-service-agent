"""
五星级酒店 — 主路由智能体 (Supervisor / Router Agent)
=============================================================
职责: 接待客人第一句话 → LLM 意图分类 → 分发到对应子 Agent

子 Agent 接入方式（二选一）:
  模式 A (本地联调): 直接 import 子 Agent 的图，调用 invoke
  模式 B (服务化部署): 通过 HTTP 调用各子 Agent 的 FastAPI 接口

当前: 客房服务 (room_service) 已实现，其余模块预留占位
"""
import logging
from typing import Annotated, Literal
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

# ★ 你的客房服务 Agent（已完工）
from room_service_agent import room_service_graph as room_graph

# ==========================================
# 日志
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] Router - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("MainRouter")

# ==========================================
# 状态 & 子 Agent 注册表
# ==========================================

# 5 个子 Agent 的标识
AGENT_ROOM       = "room_service"    # 客房服务（你的）
AGENT_FRONT      = "front_desk"      # 前台
AGENT_RESTAURANT = "restaurant"      # 餐厅
AGENT_CONCIERGE  = "concierge"       # 礼宾
AGENT_GENERAL    = "general_info"    # 总机 / 兜底

AGENT_NAMES = {
    AGENT_ROOM:       "客房服务",
    AGENT_FRONT:      "前台",
    AGENT_RESTAURANT: "餐厅",
    AGENT_CONCIERGE:  "礼宾部",
    AGENT_GENERAL:    "总机",
}


class RouterState(TypedDict):
    messages: Annotated[list, add_messages]
    target_agent: str      # LLM 决策后路由到的子 Agent 标识
    agent_response: str    # 子 Agent 的回复


# ==========================================
# LLM 意图分类 (替代简单关键词)
# ==========================================

router_llm = ChatOllama(model="qwen2.5:7b", temperature=0.1)

ROUTER_SYSTEM_PROMPT = """你是五星级酒店的总机路由系统。根据客人的消息，判断应该转接给哪个部门。

可选的部门（必须从以下5个中选一个）:
- room_service   — 客房内服务（补充物品、打扫、报修、送水、洗衣、叫醒）
- front_desk     — 前台（入住、退房、预订、账单、换房）
- restaurant     — 餐厅（点菜、菜单、餐厅预订、饮食相关问题）
- concierge      — 礼宾部（周边旅游、叫车、订票、行李、代购）
- general_info   — 总机兜底（酒店设施问询、WiFi、游泳池、健身房、非特定服务）

回复规则: 只回复一个部门标识，不要输出任何其他内容。

示例:
客人: "帮我送两瓶水到301"     → room_service
客人: "我要退房"               → front_desk
客人: "今晚餐厅有什么特色菜"   → restaurant
客人: "附近有什么好玩的"       → concierge
客人: "游泳池开到几点"         → general_info
客人: "空调坏了"               → room_service"""


def classify_intent(state: RouterState) -> dict:
    """
    用 LLM 识别客人意图，决定路由到哪个子 Agent。
    比关键词匹配更准确，能处理口语化表达。
    """
    user_msg = state["messages"][-1].content

    messages = [
        SystemMessage(content=ROUTER_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ]
    response = router_llm.invoke(messages)

    # 解析 LLM 输出，提取部门标识
    raw_output = response.content.strip().lower()
    valid_agents = [AGENT_ROOM, AGENT_FRONT, AGENT_RESTAURANT, AGENT_CONCIERGE, AGENT_GENERAL]

    target = AGENT_GENERAL  # 默认兜底
    for agent_id in valid_agents:
        if agent_id in raw_output:
            target = agent_id
            break

    logger.info("意图分类: '%s' → %s (%s)", user_msg[:50], target, AGENT_NAMES[target])
    return {"target_agent": target}


# ==========================================
# 子 Agent 调用节点
# ==========================================

def call_room_service(state: RouterState) -> dict:
    """调用你的客房服务 Agent"""
    logger.info("→ 转接 [客房服务 Agent]")

    user_msg = state["messages"][-1]
    # 使用 room_service 专用的 thread_id，确保客房对话记忆连贯
    config = {"configurable": {"thread_id": "router_room_service"}}

    try:
        result = room_graph.invoke(
            {"messages": [HumanMessage(content=user_msg.content)]},
            config=config,
        )
        reply = result["messages"][-1].content
    except Exception as e:
        logger.error("客房服务 Agent 异常: %s", str(e))
        reply = "非常抱歉，客房服务系统暂不可用。已为您转接前台（电话：0000），工作人员会立即处理。"

    return {"agent_response": reply}


def call_front_desk(state: RouterState) -> dict:
    """调用前台 Agent（占位）"""
    logger.info("→ 转接 [前台 Agent] — 待同事开发")
    return {"agent_response": "已为您转接前台。入住/退房/预订服务请前往酒店大堂前台，或拨打0000。【待同事接入】"}


def call_restaurant(state: RouterState) -> dict:
    """调用餐厅 Agent（占位）"""
    logger.info("→ 转接 [餐厅 Agent] — 待同事开发")
    return {"agent_response": "已为您转接餐饮部。如需预订餐位或了解菜单，请前往1楼云端餐厅或拨打0000。【待同事接入】"}


def call_concierge(state: RouterState) -> dict:
    """调用礼宾 Agent（占位）"""
    logger.info("→ 转接 [礼宾 Agent] — 待同事开发")
    return {"agent_response": "已为您转接礼宾部。旅游咨询、叫车、订票等服务请前往大堂礼宾台或拨打0000。【待同事接入】"}


def call_general(state: RouterState) -> dict:
    """调用总机兜底 Agent（占位）"""
    logger.info("→ 转接 [总机 Agent] — 待同事开发")
    return {"agent_response": "您好，这是酒店总机。如需帮助请告知具体需求，或拨打前台电话0000。【待同事接入】"}


def format_response(state: RouterState) -> dict:
    """将子 Agent 的回复写入消息流"""
    reply = state.get("agent_response", "抱歉，系统暂时无法处理您的请求。")
    return {"messages": [HumanMessage(content=reply)]}


# ==========================================
# 路由函数
# ==========================================

def route_to_agent(state: RouterState) -> Literal[
    "room_service", "front_desk", "restaurant", "concierge", "general_info"
]:
    """根据 LLM 分类结果，路由到对应子 Agent"""
    target = state["target_agent"]
    if target == AGENT_ROOM:
        return "room_service"
    elif target == AGENT_FRONT:
        return "front_desk"
    elif target == AGENT_RESTAURANT:
        return "restaurant"
    elif target == AGENT_CONCIERGE:
        return "concierge"
    else:
        return "general_info"


# ==========================================
# 构建主路由图
# ==========================================

def build_router_graph():
    builder = StateGraph(RouterState)

    # 注册节点
    builder.add_node("classify", classify_intent)
    builder.add_node("room_service", call_room_service)
    builder.add_node("front_desk", call_front_desk)
    builder.add_node("restaurant", call_restaurant)
    builder.add_node("concierge", call_concierge)
    builder.add_node("general_info", call_general)
    builder.add_node("format", format_response)

    # 流转
    builder.add_edge(START, "classify")
    builder.add_conditional_edges(
        "classify", route_to_agent,
        {
            "room_service":  "room_service",
            "front_desk":    "front_desk",
            "restaurant":    "restaurant",
            "concierge":     "concierge",
            "general_info":  "general_info",
        }
    )
    # 所有子 Agent 处理完 → 格式化输出 → 结束
    builder.add_edge("room_service", "format")
    builder.add_edge("front_desk", "format")
    builder.add_edge("restaurant", "format")
    builder.add_edge("concierge", "format")
    builder.add_edge("general_info", "format")
    builder.add_edge("format", END)

    mem = MemorySaver()
    return builder.compile(checkpointer=mem)


main_hotel_agent = build_router_graph()
logger.info("主路由 Agent 编译完成 (LLM 意图分类 + 5路分发)")


# ==========================================
# 对外接口
# ==========================================

def route_message(message: str, session_id: str = "default") -> str:
    """
    总控统一入口：客人消息进来 → 分类 → 分发 → 返回最终回复。

    Args:
        message: 客人的原始消息
        session_id: 会话标识

    Returns:
        子 Agent 的最终回复
    """
    config = {"configurable": {"thread_id": session_id}}
    try:
        result = main_hotel_agent.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=config,
        )
        return result["messages"][-1].content
    except Exception as e:
        logger.error("路由处理异常: %s", str(e))
        return "非常抱歉，系统暂时遇到问题。请致电前台（电话：0000），工作人员会立即为您服务。"


# ==========================================
# 自测
# ==========================================

if __name__ == "__main__":
    print("=" * 60)
    print("  五星级酒店 — 多智能体路由系统 测试")
    print("=" * 60)
    print("  已接入: 客房服务 Agent (你的模块)")
    print("  占位中: 前台 | 餐厅 | 礼宾 | 总机")
    print("=" * 60)

    test_cases = [
        "帮我送两瓶矿泉水到301",
        "302房间空调不制冷",
        "我想退房",
        "今晚有什么好吃的",
        "游泳池开到几点",
    ]

    for i, msg in enumerate(test_cases, 1):
        result = route_message(msg, session_id=f"test_{i}")
        print(f"\n[测试 {i}] 客人: {msg}")
        print(f"        回复: {result}")

    # 交互模式（仅终端直接运行时）
    try:
        print("\n" + "=" * 60)
        print("  交互模式 (输入 quit 退出)")
        print("=" * 60)
        while True:
            user_input = input("\n客人: ")
            if user_input.lower() == "quit":
                break
            reply = route_message(user_input, session_id="interactive")
            print(f"酒店: {reply}")
    except (EOFError, KeyboardInterrupt):
        print("\n再见！")
