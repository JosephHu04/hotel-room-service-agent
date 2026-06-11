"""
clarify_builder.py — 澄清追问构建节点
=======================================
BRD 对齐: §6.1 NeedClarify 机制 / §6.1.1 触发条件 / §6.1.2 字段规范 / §6.1.5 强约束

当流水线中任何一个校验节点失败时（slot_validator、capability_gate、risk_checker），
流程走到本节点，统一生成标准化的澄清追问。

核心职责:
  1. 从 decision_trace 中找到失败原因
  2. 按 BRD §6.1.5 构建 NeedClarify（14 个 reason_code 各有必填字段）
  3. 生成自然语言追问消息给客人
  4. 如果是二次确认场景，优先显示 confirm_action
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger("ClarifyBuilder")

# ============================================================
# 第一部分: 配置加载
# ============================================================

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

_slot_defs: Optional[dict] = None  # slot_name → slot_def


def _load_config():
    global _slot_defs
    if _slot_defs is not None:
        return
    with open(os.path.join(_CONFIG_DIR, "slot_definitions.json"), "r", encoding="utf-8") as f:
        slots_list = json.load(f)["slots"]
    _slot_defs = {s["name"]: s for s in slots_list}
    logger.info("澄清构建器初始化: %d 个槽位定义", len(_slot_defs))


# ============================================================
# 第二部分: 话术模板
# ============================================================

CLARIFY_TEMPLATES = {
    "missing_required_slot": {
        "template": "请问您需要{slot_desc}呢？",
        "default": "请问您能补充一下{slot_desc}吗？",
    },
    "invalid_enum": {
        "template": "抱歉，{value}不在可选范围内。{slot_desc}可选：{candidates}",
        "default": "抱歉，您说的我不太确定。{slot_desc}可选：{candidates}",
    },
    "out_of_range_clamped": {
        "template": "{slot_desc}已自动调整为{value}{unit}（原值超出范围）。",
        "default": "{slot_desc}已自动调整。",
    },
    "ambiguous_entity": {
        "template": "您指的是哪个呢？可选：{candidates}",
        "default": "有多个可能的选项，请问您指的是哪个？",
    },
    "entity_not_found": {
        "template": "请问您的{slot_desc}是什么？",
        "default": "请问具体是哪个呢？",
    },
    "intent_conflict": {
        "template": "您的需求我理解到了几种可能：{candidates}。请问您主要是想做哪一个？",
        "default": "您的需求有几种可能，能再具体说说吗？",
    },
    "capability_unsupported": {
        "template": "抱歉，当前设备不支持{intent}操作。{device_type}设备支持：{candidates}",
        "default": "抱歉，当前设备不支持这个操作。",
    },
    "risky_action_need_confirm": {
        "template": "为了您的安全，需要确认：{summary}。请回复「确认」继续，或「取消」放弃。",
        "default": "请确认此操作。",
    },
    "parse_time_failed": {
        "template": "抱歉，'{value}' 我没能解析成具体时间。请用 HH:MM 格式或「早上7点」这样的表达。",
        "default": "请问具体是什么时间呢？",
    },
    "parse_duration_failed": {
        "template": "抱歉，'{value}' 我没能解析成具体时长。请用数字表示，如「30分钟」。",
        "default": "请问具体多长时间呢？",
    },
    "low_confidence": {
        "template": "您说的是{candidates}吗？请确认一下。",
        "default": "抱歉我没太理解，能再说一遍吗？",
    },
    "device_unavailable": {
        "template": "抱歉，{value} 不可用。请检查后再试。",
        "default": "抱歉，该设备不可用。",
    },
    "out_of_scope": {
        "template": "抱歉，我是酒店客房服务助手，无法处理该问题。如有需要请联系前台（电话：0000）。",
        "default": "抱歉，无法处理该问题。",
    },
}

# 槽位中文名映射
SLOT_CN_NAMES = {
    "request_type": "服务类型",
    "location": "房间号",
    "details": "具体内容",
    "priority": "优先级",
    "alarm_action": "闹钟操作",
    "alarm_id": "闹钟编号",
    "duration": "时长",
    "label": "标签/名称",
    "language": "语言",
    "repeat": "重复规则",
    "time": "时间",
}


def _slot_desc(name: str) -> str:
    return SLOT_CN_NAMES.get(name, name)


# ============================================================
# 第三部分: 核心逻辑
# ============================================================

def _find_failure_reason(traces: list) -> Optional[dict]:
    """从 decision_trace 中找到第一个失败/阻塞记录"""
    for trace in reversed(traces):  # 从最新开始
        if isinstance(trace, dict):
            result = trace.get("result", "")
            if result in ("fail", "blocked", "cancelled", "invalid", "clamped"):
                return trace
    return None


def build_clarify(state: dict) -> dict:
    """
    根据 state 构建标准化的澄清输出。

    Args:
        state: 完整的 State

    Returns:
        {
            "reason_code": "missing_required_slot",
            "clarify_slot": "details",
            "candidates": [...],
            "message": "请问您需要送什么物品呢？",
            "structured": {...},  # 完整 NeedClarify 结构
        }
    """
    _load_config()

    traces = state.get("decision_trace") or []
    raw_intents = state.get("raw_intents") or []
    raw_slots = state.get("raw_slots") or {}
    raw_entities = state.get("raw_entities") or {}
    confirm_pending = state.get("confirm_pending", False)
    confirm_action = state.get("confirm_action", {})

    fallback_reason = "low_confidence"
    clarify_slot = ""
    candidates = []
    message = "抱歉，我没完全理解，能再说一遍吗？"
    intent_name = raw_intents[0].get("L1", "") if raw_intents else ""

    # ─── 优先级 1: 二次确认 ───
    if confirm_pending and confirm_action:
        summary = confirm_action.get("summary", "此操作")
        return {
            "reason_code": "risky_action_need_confirm",
            "clarify_slot": "",
            "candidates": [],
            "message": CLARIFY_TEMPLATES["risky_action_need_confirm"]["template"].format(
                summary=summary
            ),
            "confirm_action": confirm_action,
        }

    # ─── 优先级 2: 从 trace 推断 ───
    failure = _find_failure_reason(traces)

    if failure:
        reason = failure.get("reason", "")
        reason_code = failure.get("reason_code", fallback_reason)
        slot_name = failure.get("slot", "")

        # ─── missing_required_slot ───
        if reason == "missing_required_slot" or reason_code == "missing_required_slot":
            clarify_slot = slot_name
            slot_def = _slot_defs.get(slot_name, {})
            candidates = slot_def.get("enum", []) if slot_def.get("type") == "enum" else []
            message = f"请问您的{_slot_desc(slot_name)}是什么呢？"
            if candidates:
                message += f" 可选：{'/'.join(str(c) for c in candidates)}"
            return {
                "reason_code": "missing_required_slot",
                "clarify_slot": slot_name,
                "candidates": candidates,
                "message": message,
            }

        # ─── invalid_enum ───
        if reason == "invalid_enum" or reason_code == "invalid_enum":
            clarify_slot = slot_name
            slot_def = _slot_defs.get(slot_name, {})
            allowed = slot_def.get("enum", [])
            value = raw_slots.get(slot_name, "?")
            message = CLARIFY_TEMPLATES["invalid_enum"]["template"].format(
                value=value,
                slot_desc=_slot_desc(slot_name),
                candidates="/".join(str(c) for c in allowed),
            )
            return {
                "reason_code": "invalid_enum",
                "clarify_slot": slot_name,
                "candidates": allowed,
                "message": message,
            }

        # ─── out_of_range_clamped ───
        if reason == "out_of_range_clamped" or reason_code == "out_of_range_clamped":
            slot_def = _slot_defs.get(slot_name, {})
            unit = slot_def.get("unit", "")
            clamped_to = failure.get("clamped_to", "?")
            message = CLARIFY_TEMPLATES["out_of_range_clamped"]["template"].format(
                slot_desc=_slot_desc(slot_name),
                value=clamped_to,
                unit=unit,
            )
            return {
                "reason_code": "out_of_range_clamped",
                "clarify_slot": slot_name,
                "candidates": [],
                "message": message,
            }

        # ─── capability_unsupported ───
        if reason == "capability_unsupported":
            support_list = failure.get("supported_intents", [])
            device_type = failure.get("device_type", "?")
            message = CLARIFY_TEMPLATES["capability_unsupported"]["template"].format(
                intent=intent_name,
                device_type=device_type,
                candidates="/".join(support_list),
            )
            return {
                "reason_code": "capability_unsupported",
                "clarify_slot": "",
                "candidates": support_list,
                "message": message,
            }

        # ─── low_confidence ───
        if reason_code == "low_confidence":
            intent_descs = [
                i.get("L1", "") + (f"({i.get('score', 0):.0%})" if i.get("score") else "")
                for i in raw_intents[:3]
            ]
            candidate_str = "、".join(intent_descs) if intent_descs else "?"
            message = CLARIFY_TEMPLATES["low_confidence"]["template"].format(
                candidates=candidate_str
            )
            return {
                "reason_code": "low_confidence",
                "clarify_slot": "",
                "candidates": raw_intents[:3],
                "message": message,
            }

        # ─── invalid_format (time/duration) ───
        if reason == "invalid_format":
            if slot_name == "time":
                message = CLARIFY_TEMPLATES["parse_time_failed"]["template"].format(
                    value=failure.get("original_value", raw_slots.get("time", "?"))
                )
                return {
                    "reason_code": "parse_time_failed",
                    "clarify_slot": "time",
                    "candidates": ["例如：07:00", "例如：早上7点"],
                    "message": message,
                }
            if slot_name == "duration":
                message = CLARIFY_TEMPLATES["parse_duration_failed"]["template"].format(
                    value=failure.get("original_value", raw_slots.get("duration", "?"))
                )
                return {
                    "reason_code": "parse_duration_failed",
                    "clarify_slot": "duration",
                    "candidates": ["例如：30", "例如：60"],
                    "message": message,
                }

    # ─── 优先级 3: 通用兜底 ───
    return {
        "reason_code": fallback_reason,
        "clarify_slot": clarify_slot,
        "candidates": candidates,
        "message": message,
    }


# ============================================================
# 第四部分: LangGraph 节点函数
# ============================================================

def clarify_builder_node(state: dict) -> dict:
    """
    LangGraph 节点：构建澄清追问。

    在流水线中，所有校验失败最终汇聚到本节点。
    本节点生成标准化的追问消息 + NeedClarify 结构。

    输入: 完整 State
    输出:
      - messages: 追加追问消息
      - clarify_info: NeedClarify 结构（供 response_formatter 使用）
      - result_type: "need_clarify"
    """
    result = build_clarify(state)

    from langchain_core.messages import AIMessage

    logger.info("澄清追问: reason=%s, slot=%s, candidates=%s",
                result["reason_code"], result["clarify_slot"], result["candidates"])

    # 构建结构化 NeedClarify
    clarify_struct = {
        "reason_code": result["reason_code"],
        "clarify_slot": result["clarify_slot"],
        "candidates": result["candidates"],
    }
    if result.get("confirm_action"):
        clarify_struct["confirm_action"] = result["confirm_action"]

    return {
        "messages": [AIMessage(content=result["message"])],
        "clarify_info": clarify_struct,
        "result_type": "need_clarify",
    }


# ============================================================
# 第五部分: 自测
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("clarify_builder.py 自测")
    print("=" * 60)

    # Test 1: missing_required_slot
    print("\n[Test 1] missing_required_slot → 追问房间号")
    state = {
        "decision_trace": [
            {"step": "slot_validator", "result": "fail", "slot": "location",
             "reason": "missing_required_slot", "reason_code": "missing_required_slot"}
        ],
        "raw_intents": [{"L1": "ROOM_SERVICE"}],
        "raw_slots": {"request_type": "amenity"},
        "raw_entities": {},
        "confirm_pending": False,
    }
    result = build_clarify(state)
    assert result["reason_code"] == "missing_required_slot"
    assert result["clarify_slot"] == "location"
    assert "房间号" in result["message"]
    print(f"  PASS: {result['message']}")

    # Test 2: invalid_enum
    print("\n[Test 2] invalid_enum → 提示合法值")
    state = {
        "decision_trace": [
            {"step": "slot_validator", "result": "fail", "slot": "request_type",
             "reason": "invalid_enum", "reason_code": "invalid_enum"}
        ],
        "raw_intents": [{"L1": "ROOM_SERVICE"}],
        "raw_slots": {"request_type": "唱歌"},
        "raw_entities": {},
        "confirm_pending": False,
    }
    result = build_clarify(state)
    assert result["reason_code"] == "invalid_enum"
    assert len(result["candidates"]) > 0
    print(f"  PASS: {result['message']}")

    # Test 3: risky_action_need_confirm
    print("\n[Test 3] 二次确认 → 确认消息")
    state = {
        "decision_trace": [
            {"step": "risk_checker", "result": "blocked",
             "reason_code": "risky_action_need_confirm"}
        ],
        "raw_intents": [{"L1": "HOUSEKEEPING"}],
        "raw_slots": {},
        "raw_entities": {},
        "confirm_pending": True,
        "confirm_action": {"summary": "全部房间打扫", "intent": "HOUSEKEEPING"},
    }
    result = build_clarify(state)
    assert result["reason_code"] == "risky_action_need_confirm"
    assert "确认" in result["message"]
    print(f"  PASS: {result['message']}")

    # Test 4: capability_unsupported
    print("\n[Test 4] 能力不支持 → 提示支持列表")
    state = {
        "decision_trace": [
            {"step": "capability_gate", "result": "fail",
             "reason": "capability_unsupported",
             "device_type": "light", "supported_intents": ["LIGHTING_POWER"]}
        ],
        "raw_intents": [{"L1": "HOUSEKEEPING"}],
        "raw_slots": {},
        "raw_entities": {},
        "confirm_pending": False,
    }
    result = build_clarify(state)
    assert result["reason_code"] == "capability_unsupported"
    print(f"  PASS: {result['message']}")

    # Test 5: low_confidence
    print("\n[Test 5] 低置信度 → 候选人确认")
    state = {
        "decision_trace": [
            {"step": "risk_checker", "result": "blocked",
             "reason_code": "low_confidence"}
        ],
        "raw_intents": [
            {"L1": "HOUSEKEEPING", "score": 0.4},
            {"L1": "ROOM_SERVICE", "score": 0.35},
        ],
        "raw_slots": {},
        "raw_entities": {},
        "confirm_pending": False,
    }
    result = build_clarify(state)
    assert result["reason_code"] == "low_confidence"
    print(f"  PASS: {result['message']}")

    # Test 6: out_of_range_clamped
    print("\n[Test 6] 范围越界 → 告知已调整")
    state = {
        "decision_trace": [
            {"step": "slot_validator", "result": "clamped", "slot": "duration",
             "reason": "out_of_range_clamped", "clamped_to": 10080}
        ],
        "raw_intents": [{"L1": "ALARM"}],
        "raw_slots": {"duration": 10080},
        "raw_entities": {},
        "confirm_pending": False,
    }
    result = build_clarify(state)
    assert result["reason_code"] == "out_of_range_clamped"
    assert "10080" in result["message"]
    print(f"  PASS: {result['message']}")

    print("\n" + "=" * 60)
    print("全部自测通过! clarify_builder.py 就绪。")
    print("=" * 60)
