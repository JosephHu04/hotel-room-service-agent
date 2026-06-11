"""
slot_validator.py — 槽位校验节点
=================================
BRD 对齐: §8.3 SlotDefinitions / §9 步骤6 / AC1 AC3 AC4

对 chatbot 提取的原始槽位做 4 种校验:
  1. enum 校验   — 值必须在枚举列表内，否则 invalid_enum
  2. range 校验  — 值在 [min, max] 内，越界 clamp 并标记 out_of_range_clamped
  3. required 检查 — 意图必填槽位缺失 → missing_required_slot
  4. default 补全 — 用户未填且配置有默认值 → 自动填入，标记 defaulted

使用方式:
  - LangGraph 节点: add_node("slot_validator", slot_validator_node)
  - 独立调用: validate_slots(raw_slots, intent_id) → (validated_slots, trace_list)
"""

import os
import json
import re
import logging
from typing import Any, Optional

logger = logging.getLogger("SlotValidator")

# ============================================================
# 第一部分: 配置加载（惰性 + 缓存）
# ============================================================

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

_slot_defs: Optional[list] = None
_intent_defs: Optional[list] = None
_slot_by_name: Optional[dict] = None
_intent_by_id: Optional[dict] = None


def _load_config():
    """加载配置（首次调用时读取，后续命中缓存）"""
    global _slot_defs, _intent_defs, _slot_by_name, _intent_by_id

    if _slot_defs is not None:
        return

    with open(os.path.join(_CONFIG_DIR, "slot_definitions.json"), "r", encoding="utf-8") as f:
        _slot_defs = json.load(f)["slots"]

    with open(os.path.join(_CONFIG_DIR, "intent_definitions.json"), "r", encoding="utf-8") as f:
        _intent_defs = json.load(f)["intents"]

    # 快速查找表
    _slot_by_name = {s["name"]: s for s in _slot_defs}
    _intent_by_id = {}
    for intent in _intent_defs:
        _intent_by_id[intent["id"]] = intent
        # 也按 L1 建索引（取第一个匹配的）
        if intent["L1"] not in _intent_by_id:
            _intent_by_id[intent["L1"]] = intent

    logger.info("槽位校验器初始化: %d 个槽位定义, %d 条意图", len(_slot_defs), len(_intent_defs))


# ============================================================
# 第二部分: 校验函数
# ============================================================

def _find_intent(intents: list) -> Optional[dict]:
    """从 LLM 输出的意图列表中找到主意图（score 最高的）"""
    if not intents:
        return None

    best = intents[0]
    best_score = best.get("score", 0)

    for intent in intents[1:]:
        score = intent.get("score", 0)
        if score > best_score:
            best = intent
            best_score = score

    return best


def _resolve_intent_def(intent: dict) -> Optional[dict]:
    """根据 LLM 输出的意图，从配置中找到对应的意图定义"""
    _load_config()

    # 优先用 id 匹配
    intent_id = intent.get("id", "")
    if intent_id in _intent_by_id:
        return _intent_by_id[intent_id]

    # 回退到 L1 匹配
    L1 = intent.get("L1", "")
    if L1 in _intent_by_id:
        return _intent_by_id[L1]

    # 再试：L1 可能是 intent ID（LLM 填错字段）
    if L1.startswith("SVC_") or L1.startswith("ALARM_"):
        if L1 in _intent_by_id:
            return _intent_by_id[L1]

    return None


def validate_enum(name: str, value: Any, slot_def: dict) -> dict:
    """枚举校验：值必须在 enum 列表中

    Returns:
        {"status": "valid"|"invalid", "value": ..., "message": ""}
    """
    allowed = slot_def.get("enum", [])
    if not allowed:
        return {"status": "valid", "value": value, "message": ""}

    if value in allowed:
        return {"status": "valid", "value": value, "message": ""}

    return {
        "status": "invalid",
        "value": value,
        "message": f"'{value}' 不在 {name} 的合法值列表中（合法值: {allowed}）",
    }


def validate_range(name: str, value: Any, slot_def: dict) -> dict:
    """范围校验：值必须在 [min, max] 内，越界则 clamp

    Returns:
        {"status": "valid"|"clamped", "value": ..., "original_value": ..., "message": ""}
    """
    min_val = slot_def.get("min")
    max_val = slot_def.get("max")
    if min_val is None or max_val is None:
        return {"status": "valid", "value": value, "message": ""}

    try:
        num = float(value)
    except (ValueError, TypeError):
        return {"status": "invalid", "value": value, "message": f"'{value}' 不是有效数字"}

    unit = slot_def.get("unit", "")

    if num < min_val:
        return {
            "status": "clamped",
            "value": min_val,
            "original_value": num,
            "message": f"{name} 原始值 {num}{unit} 低于下限 {min_val}{unit}，已调整为 {min_val}{unit}",
        }

    if num > max_val:
        return {
            "status": "clamped",
            "value": max_val,
            "original_value": num,
            "message": f"{name} 原始值 {num}{unit} 超出上限 {max_val}{unit}，已调整为 {max_val}{unit}",
        }

    return {"status": "valid", "value": num, "message": ""}


def validate_time_format(name: str, value: Any, slot_def: dict) -> dict:
    """时间格式校验：尝试解析 HH:MM 或口语时间表达

    Returns:
        {"status": "valid"|"invalid", "value": ..., "message": ""}
    """
    value_str = str(value).strip()

    # 尝试匹配 HH:MM 格式
    if re.match(r'^\d{1,2}:\d{2}$', value_str):
        return {"status": "valid", "value": value_str, "message": ""}

    # 尝试匹配口语时间（如 "早上7点"、"明早六点半"、"7点"）
    time_patterns = [
        r'(早上|上午|中午|下午|晚上|明早|明天)?\s*(\d{1,2})\s*[点:：]\s*(\d{1,2})?\s*(分|半)?',
        r'(\d{1,2})\s*(am|pm|AM|PM)',
    ]

    for pattern in time_patterns:
        if re.search(pattern, value_str):
            return {"status": "valid", "value": value_str, "message": ""}

    return {
        "status": "invalid",
        "value": value_str,
        "message": f"'{value_str}' 无法解析为有效时间，请使用 HH:MM 格式或'早上7点'这样的表达",
    }


def validate_duration(name: str, value: Any, slot_def: dict) -> dict:
    """时长校验：先 check 是否是数值，再 check range"""
    try:
        num = float(value)
    except (ValueError, TypeError):
        return {
            "status": "invalid",
            "value": value,
            "message": f"'{value}' 不是有效时长数值",
        }
    return validate_range(name, num, slot_def)


def validate_location_pattern(name: str, value: Any, slot_def: dict) -> dict:
    """位置格式校验：检查是否符合 pattern（房间号格式）"""
    pattern = slot_def.get("pattern", "")
    if not pattern:
        return {"status": "valid", "value": value, "message": ""}

    value_str = str(value).strip()
    if re.match(pattern, value_str):
        return {"status": "valid", "value": value_str, "message": ""}

    desc = slot_def.get("pattern_description", pattern)
    return {
        "status": "invalid",
        "value": value_str,
        "message": f"'{value_str}' 不符合 {name} 的格式要求（{desc}）",
    }


# ============================================================
# 第三部分: 主校验函数
# ============================================================

def validate_slots(
    raw_slots: dict,
    intents: list,
) -> dict:
    """
    主入口：对 LLM 输出的原始槽位做完整校验。

    Args:
        raw_slots: chatbot 输出的原始槽位字典 {slot_name: value}
        intents: chatbot 输出的意图列表 [{"L1": "...", "id": "...", "score": ...}]

    Returns:
        {
            "validated_slots": {slot_name: {"value": ..., "status": "valid"|"clamped"|"defaulted"|"invalid", "message": ""}},
            "traces": [...],          # 每条校验一个 trace
            "need_clarify": bool,     # 是否需要追问（缺 required 槽位）
            "blocking_reason": str,   # 如果 need_clarify，这里写原因
        }
    """
    _load_config()

    validated = {}
    traces = []
    need_clarify = False
    blocking_reasons = []

    # ─── Step 1: 找到主意图及其定义 ───
    intent = _find_intent(intents)
    intent_def = _resolve_intent_def(intent) if intent else None

    if intent and intent_def:
        logger.info("校验意图: %s (id=%s)", intent_def.get("L1"), intent_def.get("id"))
    else:
        logger.warning("未找到匹配的意图定义，跳过 required 检查")

    # ─── Step 2: 逐个校验 LLM 输出的槽位 ───
    for slot_name, slot_value in raw_slots.items():
        slot_def = _slot_by_name.get(slot_name)

        if slot_def is None:
            # 未知槽位：保留原始值，不校验
            validated[slot_name] = {
                "value": slot_value,
                "status": "valid",
                "message": f"未知槽位 {slot_name}，跳过校验",
            }
            continue

        slot_type = slot_def.get("type", "")
        result = {"status": "valid", "value": slot_value, "message": ""}

        # 根据类型分发校验
        if slot_type == "enum":
            result = validate_enum(slot_name, slot_value, slot_def)
        elif slot_type == "range":
            result = validate_range(slot_name, slot_value, slot_def)
        elif slot_type == "time_format":
            result = validate_time_format(slot_name, slot_value, slot_def)
        elif slot_type == "free_text":
            # free_text 不做内容校验，但如果有 pattern 则检查格式
            if "pattern" in slot_def:
                result = validate_location_pattern(slot_name, slot_value, slot_def)
        elif slot_type == "string":
            result = {"status": "valid", "value": str(slot_value), "message": ""}

        validated[slot_name] = result

        # 生成 trace
        trace_rule_id = slot_def.get("id", "")

        if result["status"] == "invalid":
            traces.append({
                "step": "slot_validator",
                "result": "fail",
                "rule_id": trace_rule_id,
                "slot": slot_name,
                "reason": "invalid_enum" if slot_type == "enum" else "invalid_format",
                "message": result.get("message", ""),
            })
            need_clarify = True
            blocking_reasons.append(result.get("message", f"{slot_name} 校验失败"))

        elif result["status"] == "clamped":
            traces.append({
                "step": "slot_validator",
                "result": "clamped",
                "rule_id": trace_rule_id,
                "slot": slot_name,
                "reason": "out_of_range_clamped",
                "original_value": result.get("original_value"),
                "clamped_to": result["value"],
                "message": result.get("message", ""),
            })

        else:
            traces.append({
                "step": "slot_validator",
                "result": "pass",
                "rule_id": trace_rule_id,
                "slot": slot_name,
                "status": result["status"],
            })

    # ─── Step 3: 检查 required 槽位 ───
    if intent_def:
        required_slots = intent_def.get("required", [])
        for req_name in required_slots:
            if req_name not in raw_slots or not raw_slots[req_name]:
                need_clarify = True
                blocking_reasons.append(f"缺少必填槽位: {req_name}")
                traces.append({
                    "step": "slot_validator",
                    "result": "fail",
                    "rule_id": "required_check",
                    "slot": req_name,
                    "reason": "missing_required_slot",
                    "message": f"意图 {intent_def.get('id')} 需要 {req_name}，但用户未提供",
                })

    # ─── Step 4: 补全 default 槽位 ───
    if intent_def:
        # 收集当前意图涉及的所有槽位
        optional_slots = intent_def.get("optional", [])
        all_relevant = set(intent_def.get("required", []) + optional_slots)

        for slot_name in all_relevant:
            if slot_name in validated:
                continue  # 已有值（LLM 提取了或已在上面校验过）

            slot_def = _slot_by_name.get(slot_name)
            if slot_def and "default" in slot_def:
                default_val = slot_def["default"]
                validated[slot_name] = {
                    "value": default_val,
                    "status": "defaulted",
                    "message": f"未指定 {slot_name}，已自动填充默认值: {default_val}",
                }
                traces.append({
                    "step": "slot_validator",
                    "result": "defaulted",
                    "rule_id": slot_def.get("id", ""),
                    "slot": slot_name,
                    "defaulted_to": default_val,
                    "message": f"未指定 {slot_name}，已自动填充默认值: {default_val}",
                })

    # ─── Step 5: 汇总 ───
    if need_clarify:
        logger.warning("槽位校验未通过: %s", "; ".join(blocking_reasons))
    else:
        logger.info("全部槽位校验通过 (%d 个槽位)", len(validated))

    return {
        "validated_slots": validated,
        "traces": traces,
        "need_clarify": need_clarify or False,
        "blocking_reason": "; ".join(blocking_reasons) if blocking_reasons else "",
    }


# ============================================================
# 第四部分: LangGraph 节点函数
# ============================================================

def slot_validator_node(state: dict) -> dict:
    """
    LangGraph 节点：对 chatbot 输出的槽位做校验。

    输入 state 字段:
      - raw_intents: LLM 输出的意图列表
      - raw_slots: LLM 输出的原始槽位字典

    输出 state 更新:
      - validated_slots: 校验后的槽位（含 status）
      - decision_trace: 追加 trace 记录
      - need_clarify: 是否需要追问
    """
    raw_intents = state.get("raw_intents") or []
    raw_slots = state.get("raw_slots") or {}

    if not raw_intents:
        logger.info("slot_validator: 无意图，跳过")
        return {
            "validated_slots": {},
            "need_clarify": True,
        }

    result = validate_slots(raw_slots, raw_intents)

    # 追加到已有的 decision_trace
    existing_traces = state.get("decision_trace") or []

    return {
        "validated_slots": result["validated_slots"],
        "need_clarify": result["need_clarify"],
        "decision_trace": existing_traces + result["traces"],
    }


# ============================================================
# 第五部分: 自测
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("slot_validator.py 自测")
    print("=" * 60)

    # Test 1: 正常场景 — 送物品，槽位齐全
    print("\n[Test 1] 正常: 送矿泉水到301")
    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}]
    raw_slots = {
        "request_type": "amenity",
        "location": "301",
        "details": "两瓶矿泉水",
    }
    result = validate_slots(raw_slots, intents)
    assert result["need_clarify"] is False
    assert result["validated_slots"]["request_type"]["status"] == "valid"
    assert result["validated_slots"]["priority"]["status"] == "defaulted"
    print("  PASS: request_type=valid, priority=defaulted")

    # Test 2: 缺 required 槽位
    print("\n[Test 2] 缺 required: 送东西但没说类型")
    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}]
    raw_slots = {
        "location": "301",
        "details": "两瓶矿泉水",
        # 注意：没有 request_type
    }
    result = validate_slots(raw_slots, intents)
    assert result["need_clarify"] is True
    assert "request_type" in result["blocking_reason"]
    print(f"  PASS: need_clarify=True, reason={result['blocking_reason'][:60]}")

    # Test 3: 枚举值不合法
    print("\n[Test 3] 非法枚举: request_type='唱歌'")
    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}]
    raw_slots = {
        "request_type": "唱歌",
        "location": "301",
    }
    result = validate_slots(raw_slots, intents)
    assert result["need_clarify"] is True
    assert result["validated_slots"]["request_type"]["status"] == "invalid"
    print(f"  PASS: request_type=invalid, need_clarify=True")

    # Test 4: 数值越界 clamp
    print("\n[Test 4] 数值越界: duration=50000 分钟")
    intents = [{"L1": "ALARM", "id": "ALARM_001", "score": 0.95}]
    raw_slots = {
        "time": "07:00",
        "duration": 50000,
    }
    result = validate_slots(raw_slots, intents)
    assert result["validated_slots"]["duration"]["status"] == "clamped"
    assert result["validated_slots"]["duration"]["value"] == 10080.0
    print(f"  PASS: duration clamped 50000→10080")

    # Test 5: 叫醒缺少 time
    print("\n[Test 5] ALARM 缺 time")
    intents = [{"L1": "ALARM", "id": "ALARM_001", "score": 0.95}]
    raw_slots = {
        "duration": 60,
    }
    result = validate_slots(raw_slots, intents)
    assert result["need_clarify"] is True
    assert "time" in result["blocking_reason"]
    print(f"  PASS: need_clarify=True, reason={result['blocking_reason'][:60]}")

    # Test 6: 房间号格式校验
    print("\n[Test 6] 房间号格式: location='abc' 不匹配")
    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}]
    raw_slots = {
        "request_type": "amenity",
        "location": "abc",
    }
    result = validate_slots(raw_slots, intents)
    assert result["validated_slots"]["location"]["status"] == "invalid"
    print(f"  PASS: location=invalid (不匹配 \\d{{3,4}})")

    print("\n" + "=" * 60)
    print("全部自测通过! slot_validator.py 就绪。")
    print("=" * 60)
