"""
response_formatter.py — 最终输出格式化节点
============================================
BRD 对齐: §5.2 输出契约 / §11 AC5（实体/动作可追溯）

流水线的最后一个节点，收集全链路所有信息，组装成标准化 FinalOutput。

三种输出模式:
  execute       → 含 final_intent + final_slots + resolved_entities + decision_trace
  need_clarify  → 含 clarify_info（reason_code + clarify_slot + candidates）
  reject        → 含拒绝原因 + 礼貌话术
"""

import logging
from typing import Optional

logger = logging.getLogger("ResponseFormatter")


# ============================================================
# 第一部分: 辅助函数
# ============================================================

def _result_type(state: dict) -> str:
    """从 state 推断最终的 result_type"""
    if state.get("is_safe") == "UNSAFE":
        return "reject"
    if state.get("need_clarify"):
        return "need_clarify"
    # 如果有 final_intent 且不 need_clarify → execute
    if state.get("raw_intents"):
        return "execute"
    return "reject"


def _build_final_intent(state: dict) -> Optional[dict]:
    """从 raw_intents 提取 final_intent"""
    intents = state.get("raw_intents") or []
    if not intents:
        return None
    best = intents[0]
    return {
        "L1": best.get("L1", ""),
        "L2": best.get("L2", "DEFAULT"),
        "L3": best.get("L3", "DEFAULT"),
        "id": best.get("id", ""),
        "score": best.get("score", 1.0),
    }


def _build_final_slots(state: dict) -> dict:
    """从 validated_slots 或 raw_slots 提取最终槽位"""
    raw = state.get("validated_slots") or state.get("raw_slots") or {}
    result = {}
    for name, val in raw.items():
        if isinstance(val, dict):
            result[name] = {
                "value": val.get("value"),
                "status": val.get("status", "raw"),
            }
            if val.get("message"):
                result[name]["message"] = val["message"]
        else:
            result[name] = {"value": val, "status": "raw"}
    return result


def _build_decision_trace(state: dict) -> list:
    """收集全链路 decision_trace"""
    traces = state.get("decision_trace") or []
    # 添加配置版本信息
    traces.append({
        "step": "response_formatter",
        "result": "summary",
        "config_version": "BRD-2026-01-23",
        "total_steps": len(traces),
    })
    return traces


# ============================================================
# 第二部分: 主入口
# ============================================================

def format_response(state: dict) -> dict:
    """
    将 State 中的所有信息组装成 FinalOutput。

    Args:
        state: 完整的 State

    Returns:
        {
            "result_type": "execute" | "need_clarify" | "reject",
            "final_intent": {...},
            "final_slots": {...},
            "resolved_entities": {...},
            "clarify_info": {...},       # need_clarify 时有
            "decision_trace": [...],
            "structured_output": {...},  # 完整 FinalOutput dict
        }
    """
    result_type = _result_type(state)
    final_intent = _build_final_intent(state)
    final_slots = _build_final_slots(state)
    resolved_entities = state.get("raw_entities") or {}
    clarify_info = state.get("clarify_info", None)
    decision_trace = _build_decision_trace(state)

    # 构建完整 FinalOutput
    structured = {
        "result_type": result_type,
        "decision_trace": decision_trace,
    }

    if final_intent:
        structured["final_intent"] = final_intent

    if final_slots:
        structured["final_slots"] = final_slots

    if resolved_entities:
        structured["resolved_entities"] = resolved_entities

    if clarify_info:
        structured["clarify_info"] = clarify_info

    if state.get("session_id"):
        structured["session_id"] = state["session_id"]

    # 生成最终回复文本
    # （在实际使用中，最后一条 AIMessage 就是给客人看的回复）
    messages = state.get("messages") or []
    response_text = ""
    for msg in reversed(messages):
        if hasattr(msg, "content") and msg.content:
            # 取最后一条 AI 消息
            if getattr(msg, "type", "") == "ai" or "AIMessage" in str(type(msg)):
                response_text = msg.content
                break

    if not response_text:
        # 兜底
        if result_type == "execute":
            response_text = "好的，已为您处理。"
        elif result_type == "need_clarify":
            response_text = "请问还有什么需要补充的吗？"
        else:
            response_text = "抱歉，无法处理该问题。如有需要请联系前台（电话：0000）。"

    structured["response_text"] = response_text

    logger.info("最终输出: result_type=%s, intent=%s, slots=%d, traces=%d",
                result_type,
                final_intent.get("L1") if final_intent else "N/A",
                len(final_slots),
                len(decision_trace))

    return {
        "structured_output": structured,
        "result_type": result_type,
        "decision_trace": decision_trace,
    }


# ============================================================
# 第三部分: LangGraph 节点函数
# ============================================================

def response_formatter_node(state: dict) -> dict:
    """
    LangGraph 节点：最终输出格式化。

    这是流水线的最后一个节点，收集全链路信息并组装成标准化的 FinalOutput。
    """
    result = format_response(state)
    structured = result["structured_output"]

    # 追加 structured_output 到 state
    return {
        "structured_output": structured,
        "result_type": structured["result_type"],
        "decision_trace": result["decision_trace"],
    }


# ============================================================
# 第四部分: 自测
# ============================================================

if __name__ == "__main__":
    from langchain_core.messages import AIMessage

    print("=" * 60)
    print("response_formatter.py 自测")
    print("=" * 60)

    # Test 1: execute 模式
    print("\n[Test 1] execute → 完整输出")
    state = {
        "is_safe": "SAFE",
        "need_clarify": False,
        "raw_intents": [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}],
        "validated_slots": {
            "request_type": {"value": "amenity", "status": "valid"},
            "location": {"value": "301", "status": "valid"},
            "priority": {"value": "normal", "status": "defaulted"},
        },
        "raw_entities": {"room": "301", "item": "矿泉水"},
        "decision_trace": [
            {"step": "slot_validator", "result": "pass"},
            {"step": "risk_checker", "result": "pass"},
        ],
        "messages": [AIMessage(content="好的，已为您安排配送矿泉水到301。")],
    }
    result = format_response(state)
    assert result["result_type"] == "execute"
    assert result["structured_output"]["final_intent"]["L1"] == "ROOM_SERVICE"
    assert len(result["structured_output"]["final_slots"]) == 3
    print(f"  PASS: type=execute, intent=ROOM_SERVICE, 3 slots, 3 traces")

    # Test 2: need_clarify 模式
    print("\n[Test 2] need_clarify → 含 clarify_info")
    state = {
        "is_safe": "SAFE",
        "need_clarify": True,
        "raw_intents": [{"L1": "ROOM_SERVICE"}],
        "raw_slots": {"request_type": "amenity"},
        "raw_entities": {},
        "clarify_info": {"reason_code": "missing_required_slot", "clarify_slot": "location"},
        "decision_trace": [
            {"step": "slot_validator", "result": "fail", "reason": "missing_required_slot"},
        ],
        "messages": [AIMessage(content="请问您的房间号是什么呢？")],
    }
    result = format_response(state)
    assert result["result_type"] == "need_clarify"
    assert result["structured_output"]["clarify_info"]["reason_code"] == "missing_required_slot"
    print(f"  PASS: type=need_clarify, reason=missing_required_slot")

    # Test 3: reject 模式
    print("\n[Test 3] reject → 拒绝")
    state = {
        "is_safe": "UNSAFE",
        "need_clarify": True,
        "raw_intents": [],
        "raw_slots": {},
        "raw_entities": {},
        "decision_trace": [
            {"step": "guardrail", "result": "blocked"},
        ],
        "messages": [
            AIMessage(content="抱歉，无法处理该问题。请联系前台（电话：0000）。")
        ],
    }
    result = format_response(state)
    assert result["result_type"] == "reject"
    print(f"  PASS: type=reject")

    print("\n" + "=" * 60)
    print("全部自测通过! response_formatter.py 就绪。")
    print("=" * 60)
