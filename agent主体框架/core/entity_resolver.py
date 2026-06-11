"""
entity_resolver.py — 实体解析节点
===================================
BRD 对齐: §10.3 实体解析与歧义处理

Day 10: 接入 lexicon.json 实体词典，增强实体解析能力

处理逻辑:
  - 房间号提取（正则 + lexicon 模式）
  - 物品名口语→标准值映射（lexicon 同义词表）
  - 紧急程度检测（lexicon 紧急信号词）
  - 多房间号歧义检测
"""

import os
import json
import re
import logging

logger = logging.getLogger("EntityResolver")

# ── 加载实体词典 ──
_LEXICON = None
_LEXICON_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "lexicon.json")

def _load_lexicon():
    global _LEXICON
    if _LEXICON is not None:
        return _LEXICON
    try:
        with open(_LEXICON_PATH, "r", encoding="utf-8") as f:
            _LEXICON = json.load(f)
        logger.info("实体词典已加载: %d 个词条",
                    sum(len(v) for k,v in _LEXICON.get("supplies",{}).items() if isinstance(v, list)))
    except Exception:
        _LEXICON = {}
    return _LEXICON

# 房间号正则（含 lexicon 模式）
ROOM_PATTERN = re.compile(r'\b(\d{3,4})\b')
ROOM_FLEX_PATTERN = re.compile(r'\b([A-Za-z]?\d{3,4})\b')

# 需要房间号的意图
INTENTS_NEED_ROOM = ["ROOM_SERVICE", "HOUSEKEEPING", "HOTEL_CALL", "ALARM"]


def _extract_room_numbers(text: str) -> list:
    """从文本中提取所有候选房间号（含字母前缀）"""
    matches = ROOM_FLEX_PATTERN.findall(text)
    # 去重 + 规范化（大写字母前缀）
    seen = set()
    result = []
    for m in matches:
        normalized = m.upper() if any(c.isalpha() for c in m) else m
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def canonicalize_item(item_name: str) -> str:
    """将物品口语说法映射到标准名称（查 lexicon 同义词表）"""
    if not item_name:
        return item_name
    lexicon = _load_lexicon()
    supplies = lexicon.get("supplies", {})
    # 精确匹配
    if item_name in supplies:
        return item_name
    # 同义词查找
    for canonical, synonyms in supplies.items():
        if isinstance(synonyms, list):
            if item_name in synonyms or any(s in item_name for s in synonyms):
                return canonical
    return item_name


def detect_urgency(text: str) -> str:
    """检测紧急程度：urgent / high / normal"""
    lexicon = _load_lexicon()
    signals = lexicon.get("urgency_signals", {})
    for kw in signals.get("urgent", []):
        if kw in text:
            return "urgent"
    for kw in signals.get("high", []):
        if kw in text:
            return "high"
    return "normal"


def resolve_entities(state: dict) -> dict:
    """
    解析实体。

    Args:
        state: 完整 State

    Returns:
        {
            "resolved_entities": {"room": "301", "item": "矿泉水"},
            "need_clarify": bool,
            "reason_code": "",
            "clarify_slot": "",
            "candidates": [],
            "trace": {...}
        }
    """
    raw_intents = state.get("raw_intents") or []
    raw_entities = state.get("raw_entities") or {}
    slots = state.get("validated_slots") or state.get("raw_slots") or {}
    messages = state.get("messages") or []

    # 提取纯值
    pure_slots = {}
    for k, v in slots.items():
        if isinstance(v, dict) and "value" in v:
            pure_slots[k] = v["value"]
        else:
            pure_slots[k] = v

    # 拼所有可搜索文本
    search_text = ""
    for msg in messages:
        if hasattr(msg, "content"):
            search_text += " " + str(msg.content)
    search_text += " " + str(pure_slots.get("location", ""))
    search_text += " " + str(raw_entities.get("room", ""))

    resolved = {}

    # ─── 1. 房间号 ───
    room = raw_entities.get("room", "") or pure_slots.get("location", "")
    if room:
        # 验证格式
        if ROOM_PATTERN.fullmatch(str(room)):
            resolved["room"] = str(room)
            logger.info("实体解析: 房间号=%s (来源: LLM)", room)
        else:
            # 尝试从全文提取
            candidates = _extract_room_numbers(search_text)
            if len(candidates) == 1:
                resolved["room"] = candidates[0]
                logger.info("实体解析: 房间号=%s (来源: 正则提取)", candidates[0])
            elif len(candidates) > 1:
                logger.warning("实体歧义: 多个房间号 %s", candidates)
                return {
                    "resolved_entities": resolved,
                    "need_clarify": True,
                    "reason_code": "ambiguous_entity",
                    "clarify_slot": "location",
                    "candidates": candidates,
                    "trace": {
                        "step": "entity_resolver",
                        "result": "fail",
                        "reason": "ambiguous_entity",
                        "reason_code": "ambiguous_entity",
                        "candidates": candidates,
                        "message": f"检测到多个房间号: {candidates}，需要确认",
                    },
                }
    else:
        # 没房间号 → 从全文提取
        candidates = _extract_room_numbers(search_text)
        if len(candidates) == 1:
            resolved["room"] = candidates[0]
            logger.info("实体解析: 房间号=%s (来源: 正则)", candidates[0])
        elif len(candidates) > 1:
            return {
                "resolved_entities": resolved,
                "need_clarify": True,
                "reason_code": "ambiguous_entity",
                "clarify_slot": "location",
                "candidates": candidates,
                "trace": {
                    "step": "entity_resolver", "result": "fail",
                    "reason": "ambiguous_entity",
                    "candidates": candidates,
                },
            }

    # ─── 2. 检查是否需要房间号 ───
    if not resolved.get("room") and raw_intents:
        L1 = raw_intents[0].get("L1", "")
        if L1 in INTENTS_NEED_ROOM and L1 != "ALARM":
            logger.warning("实体缺失: 意图 %s 需要房间号但未找到", L1)
            return {
                "resolved_entities": resolved,
                "need_clarify": True,
                "reason_code": "entity_not_found",
                "clarify_slot": "location",
                "candidates": [],
                "trace": {
                    "step": "entity_resolver", "result": "fail",
                    "reason": "entity_not_found",
                    "reason_code": "entity_not_found",
                    "message": f"意图 {L1} 需要房间号但未找到",
                },
            }

    # ─── 3. 物品名 ───
    item = raw_entities.get("item", "") or pure_slots.get("details", "")
    if item:
        resolved["item"] = str(item)

    # ─── 3.5. 物品名标准化 ───
    item = raw_entities.get("item", "") or pure_slots.get("details", "")
    if item:
        resolved["item"] = item
        resolved["item_canonical"] = canonicalize_item(item)
        if resolved["item_canonical"] != item:
            logger.info("实体标准化: '%s' → '%s'", item, resolved["item_canonical"])

    # ─── 3.6. 紧急程度检测 ───
    urgency = detect_urgency(search_text)
    if urgency != "normal":
        resolved["urgency"] = urgency

    # ─── 4. 成功 ───
    logger.info("实体解析完成: %s", resolved)
    return {
        "resolved_entities": resolved,
        "need_clarify": False,
        "reason_code": "",
        "clarify_slot": "",
        "candidates": [],
        "trace": {
            "step": "entity_resolver",
            "result": "pass",
            "resolved": resolved,
        },
    }


# ============================================================
# LangGraph 节点
# ============================================================

def entity_resolver_node(state: dict) -> dict:
    """LangGraph 节点：实体解析"""
    result = resolve_entities(state)

    existing_traces = state.get("decision_trace") or []
    trace = result.get("trace", {})

    return {
        "resolved_entities": result["resolved_entities"],
        "need_clarify": result["need_clarify"],
        "decision_trace": existing_traces + ([trace] if trace else []),
    }


# ============================================================
# 自测
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("entity_resolver.py 自测")
    print("=" * 60)

    from langchain_core.messages import HumanMessage

    # Test 1: 正常房间号（LLM 已提取）
    print("\n[Test 1] LLM 提取了房间号 → 直接使用")
    state = {
        "raw_intents": [{"L1": "ROOM_SERVICE"}],
        "raw_entities": {"room": "301", "item": "矿泉水"},
        "raw_slots": {"location": "301"},
        "messages": [HumanMessage(content="送水到301")],
    }
    r = resolve_entities(state)
    assert r["need_clarify"] is False
    assert r["resolved_entities"]["room"] == "301"
    print(f"  PASS: room=301, need_clarify=False")

    # Test 2: 多房间号歧义
    print("\n[Test 2] 多个房间号 → ambiguous_entity")
    state = {
        "raw_intents": [{"L1": "ROOM_SERVICE"}],
        "raw_entities": {},
        "raw_slots": {"location": "301 和 302"},
        "messages": [HumanMessage(content="301和302都需要送水")],
    }
    r = resolve_entities(state)
    assert r["need_clarify"] is True
    assert r["reason_code"] == "ambiguous_entity"
    print(f"  PASS: ambiguous_entity, candidates={r['candidates']}")

    # Test 3: 没房间号 → entity_not_found
    print("\n[Test 3] 没房间号 → entity_not_found")
    state = {
        "raw_intents": [{"L1": "ROOM_SERVICE"}],
        "raw_entities": {},
        "raw_slots": {},
        "messages": [HumanMessage(content="送点东西")],
    }
    r = resolve_entities(state)
    assert r["need_clarify"] is True
    assert r["reason_code"] == "entity_not_found"
    print(f"  PASS: entity_not_found")

    # Test 4: ALARM 不需要房间号也能过
    print("\n[Test 4] ALARM 没房间号 → 不拦截")
    state = {
        "raw_intents": [{"L1": "ALARM"}],
        "raw_entities": {},
        "raw_slots": {"time": "07:00"},
        "messages": [HumanMessage(content="明早7点叫我")],
    }
    r = resolve_entities(state)
    assert r["need_clarify"] is False
    print(f"  PASS: ALARM without room → pass")

    print("\n全部自测完成! entity_resolver.py 就绪。")
