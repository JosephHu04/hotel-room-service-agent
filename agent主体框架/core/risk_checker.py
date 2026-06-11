"""
risk_checker.py — 风控红线检查节点
====================================
BRD 对齐: §7 意图级风控 / §7.1 全局红线 GR-01~10 / §6.1.6 优先级

两级检查:
  1. Intent 级风险: 查 intent_risk，高风险需二次确认
  2. 全局红线: 遍历 GR-01~10，命中则拦截

二次确认流程:
  客人说高风险操作 → risk_checker 拦截 → need_clarify("您确定要...?")
  客人回复"确认"/"好的" → confirm_pending=True → 重新进入 → 放行
  客人回复"算了" → 终止
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger("RiskChecker")

# ============================================================
# 第一部分: 配置加载（惰性 + 缓存）
# ============================================================

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

_risk_config: Optional[dict] = None
_intent_list: Optional[list] = None
_intent_by_L1: Optional[dict] = None


def _load_config():
    """加载配置（首次调用时读取，后续命中缓存）"""
    global _risk_config, _intent_list, _intent_by_L1

    if _risk_config is not None:
        return

    with open(os.path.join(_CONFIG_DIR, "risk_control.json"), "r", encoding="utf-8") as f:
        _risk_config = json.load(f)

    with open(os.path.join(_CONFIG_DIR, "intent_definitions.json"), "r", encoding="utf-8") as f:
        _intent_list = json.load(f)["intents"]

    _intent_by_L1 = {}
    for intent in _intent_list:
        _intent_by_L1[intent["L1"]] = intent

    logger.info("风控检查器初始化: %d 条意图风险, %d 条全局红线",
                len(_risk_config.get("intent_risk", {})),
                len(_risk_config.get("global_rules", [])))


# ============================================================
# 第二部分: 确认/取消检测
# ============================================================

CONFIRM_KEYWORDS = ["确认", "好的", "行", "可以", "是的", "对", "嗯", "好", "ok", "yes", "确定"]
CANCEL_KEYWORDS = ["算了", "不用了", "取消", "不要", "别", "no", "cancel"]


def _is_confirm(text: str) -> bool:
    """检测用户消息是否是确认"""
    text_lower = text.strip().lower()
    return any(kw in text_lower for kw in CONFIRM_KEYWORDS)


def _is_cancel(text: str) -> bool:
    """检测用户消息是否是取消"""
    text_lower = text.strip().lower()
    return any(kw in text_lower for kw in CANCEL_KEYWORDS)


# ============================================================
# 第三部分: 核心逻辑
# ============================================================

def _resolve_intent_L1(intents: list) -> Optional[str]:
    """从 LLM 输出的意图中找到主意图的 L1"""
    if not intents:
        return None

    intent = intents[0]
    L1 = intent.get("L1", "")

    # 如果 L1 是 intent ID（如 SVC_HK_001），转换
    _load_config()
    if L1 in _intent_by_L1:
        return L1
    if L1.startswith("SVC_") or L1.startswith("ALARM_"):
        # 从 ID 推断
        if "HK" in L1:
            return "HOUSEKEEPING"
        elif "ROOM" in L1:
            return "ROOM_SERVICE"
        elif "CALL" in L1:
            return "HOTEL_CALL"
        elif "ALARM" in L1:
            return "ALARM"

    return L1


def _check_intent_risk(intents: list, slots: dict) -> dict:
    """
    Intent 级风险检查。

    查 risk_control.json 的 intent_risk:
      - require_confirm=true → 高风险，需要二次确认
      - ALARM: 只有 delete/close 需要确认

    Returns:
        {"triggered": bool, "level": "", "reason": "", "confirm_action": {}}
    """
    _load_config()

    L1 = _resolve_intent_L1(intents)
    if L1 is None:
        return {"triggered": False, "level": "", "reason": "", "confirm_action": {}}

    intent_risk = _risk_config.get("intent_risk", {}).get(L1)
    if intent_risk is None:
        return {"triggered": False, "level": "", "reason": "", "confirm_action": {}}

    level = intent_risk.get("level", "low")
    require_confirm = intent_risk.get("require_confirm", False)

    # ALARM 特殊处理: 只有 delete/close 需要确认
    if L1 == "ALARM" and not require_confirm:
        alarm_action = slots.get("alarm_action", "")
        confirm_actions = intent_risk.get("confirm_actions", [])
        if alarm_action in confirm_actions:
            require_confirm = True

    if not require_confirm:
        return {"triggered": False, "level": level, "reason": "", "confirm_action": {}}

    # 构建确认摘要
    intent_name = L1
    scope = slots.get("scope", "single")
    details = slots.get("details", "")
    location = slots.get("location", "")
    time = slots.get("time", "")

    confirm_action = {
        "intent": intent_name,
        "summary": f"{intent_name} 操作",
    }
    if location:
        confirm_action["room"] = location
    if details:
        confirm_action["details"] = details
        confirm_action["summary"] = f"{details} → {location}" if location else details
    if time:
        confirm_action["time"] = time

    return {
        "triggered": True,
        "level": level,
        "reason": f"{L1} 为{level}风险操作，需要二次确认",
        "confirm_action": confirm_action,
    }


def _check_global_rules(intents: list, slots: dict, entities: dict, state: dict) -> list:
    """
    全局红线 GR-01~10 检查。

    逐一检查 10 条红线，返回所有命中的规则。

    当前可自动检查的:
      - GR-03: 不可逆操作（高风险 intent）
      - GR-04: 能力不支持（capability_gate 已查，此处复查）
      - GR-05: 枚举非法（slot_validator 已查）
      - GR-09: 置信度不足
      - GR-10: 缺目标（缺 required 槽位）

    需要后续节点支持的（暂手工检查）:
      - GR-01: 实体歧义（entity_resolver — Day 9）
      - GR-02: 范围不明确（scope=all 未确认）
      - GR-06: 时间解析失败（slot_validator 已查）
      - GR-07: 意图冲突（多个意图 score 接近）
      - GR-08: 设备不可用（entity_resolver — Day 9）
    """
    _load_config()

    triggered = []
    global_rules = _risk_config.get("global_rules", [])

    L1 = _resolve_intent_L1(intents)
    top_intent = intents[0] if intents else {}

    for rule in global_rules:
        rule_id = rule.get("id", "")
        reason_code = rule.get("reason_code", "")

        # GR-03: 不可逆/高影响操作 — 所有高风险 intent
        if rule_id == "GR-03":
            risk_result = _check_intent_risk(intents, slots)
            if risk_result["triggered"]:
                triggered.append({
                    "rule_id": rule_id,
                    "reason_code": "risky_action_need_confirm",
                    "message": rule.get("trigger_condition", ""),
                    "requirement": rule.get("requirement", ""),
                })

        # GR-05: 枚举非法 — 检查 validated_slots 中是否有 invalid
        if rule_id == "GR-05":
            validated = state.get("validated_slots") or {}
            for name, slot_info in validated.items():
                if isinstance(slot_info, dict) and slot_info.get("status") == "invalid":
                    triggered.append({
                        "rule_id": rule_id,
                        "reason_code": "invalid_enum",
                        "message": f"槽位 {name} 枚举值不合法: {slot_info.get('message', '')}",
                        "requirement": rule.get("requirement", ""),
                    })
                    break

        # GR-09: 置信度不足
        if rule_id == "GR-09":
            score = top_intent.get("score", 1.0)
            if score < 0.5:  # 阈值可配置
                triggered.append({
                    "rule_id": rule_id,
                    "reason_code": "low_confidence",
                    "message": f"LLM 置信度仅 {score:.2f}，不足以支撑唯一决策",
                    "requirement": rule.get("requirement", ""),
                })

        # GR-10: 缺目标 — 检查 required 槽位缺失
        if rule_id == "GR-10":
            if state.get("need_clarify") and "missing_required_slot" in str(
                state.get("decision_trace", [])
            ):
                triggered.append({
                    "rule_id": rule_id,
                    "reason_code": "missing_required_slot",
                    "message": rule.get("trigger_condition", ""),
                    "requirement": rule.get("requirement", ""),
                })

    return triggered


def _prioritize(triggered: list) -> list:
    """按 BRD §6.1.6 优先级排序，取最高优先级的作为主 reason_code"""
    _load_config()
    priority_order = _risk_config.get("clarify_priority", {}).get("order", [])

    if not priority_order:
        return triggered

    # 构建 reason_code → rank 的映射
    rank_map = {item["reason_code"]: item["rank"] for item in priority_order}

    # 排序：rank 越小越优先
    triggered.sort(key=lambda r: rank_map.get(r.get("reason_code", ""), 999))

    return triggered


# ============================================================
# 第四部分: 主入口
# ============================================================

def check_risks(intents: list, slots: dict, entities: dict, state: dict) -> dict:
    """
    主入口：完整风控检查。

    Args:
        intents: LLM 输出的意图列表
        slots: 当前槽位（优先 validated_slots，回退 raw_slots）
        entities: 实体字典
        state: 完整 State（用于读取上游校验结果）

    Returns:
        {
            "passed": True/False,
            "need_confirm": bool,        # 是否需要二次确认
            "confirm_action": {},         # 确认摘要（给客人看的）
            "triggered_rules": [...],     # 命中的红线
            "primary_reason": "",         # 主原因码（优先级最高）
            "additional_reasons": [...],  # 其他原因（trace 用）
            "traces": [...],
        }
    """
    _load_config()

    traces = []
    all_triggered = []

    # ─── 1. Intent 级风险 ───
    intent_risk = _check_intent_risk(intents, slots)
    if intent_risk["triggered"]:
        all_triggered.append({
            "rule_id": "INTENT_RISK",
            "reason_code": "risky_action_need_confirm",
            "level": intent_risk["level"],
            "message": intent_risk["reason"],
            "confirm_action": intent_risk["confirm_action"],
        })

    # ─── 2. 全局红线 ───
    global_triggers = _check_global_rules(intents, slots, entities, state)
    all_triggered.extend(global_triggers)

    # ─── 3. 按优先级排序 ───
    all_triggered = _prioritize(all_triggered)

    if not all_triggered:
        logger.info("风控检查通过: 无红线触发")
        return {
            "passed": True,
            "need_confirm": False,
            "confirm_action": {},
            "triggered_rules": [],
            "primary_reason": "",
            "additional_reasons": [],
            "traces": [{"step": "risk_checker", "result": "pass", "message": "风控检查通过"}],
        }

    # ─── 4. 汇总 ───
    primary = all_triggered[0]
    additional = all_triggered[1:]

    logger.warning("风控触发: 主=%s, 共%d条",
                   primary.get("reason_code", "?"), len(all_triggered))

    # 生成 traces
    for t in all_triggered:
        traces.append({
            "step": "risk_checker",
            "result": "blocked",
            "rule_id": t.get("rule_id", ""),
            "reason_code": t.get("reason_code", ""),
            "message": t.get("message", ""),
        })

    return {
        "passed": False,
        "need_confirm": primary.get("reason_code") == "risky_action_need_confirm",
        "confirm_action": primary.get("confirm_action", {}),
        "triggered_rules": all_triggered,
        "primary_reason": primary.get("reason_code", ""),
        "additional_reasons": [a.get("reason_code", "") for a in additional],
        "traces": traces,
    }


# ============================================================
# 第五部分: LangGraph 节点函数
# ============================================================

def risk_checker_node(state: dict) -> dict:
    """
    LangGraph 节点：风控红线检查。

    输入 state 字段:
      - raw_intents
      - validated_slots / raw_slots
      - raw_entities
      - confirm_pending: 是否已确认（二次确认流程）
      - messages: 用于检测确认/取消关键词

    输出 state 更新:
      - need_clarify: True 如果需要确认或拦截
      - confirm_pending: 是否进入等待确认状态
      - decision_trace: 追加风控 trace
    """
    _load_config()

    intents = state.get("raw_intents") or []
    slots = state.get("validated_slots") or state.get("raw_slots") or {}
    entities = state.get("raw_entities") or {}
    confirm_pending = state.get("confirm_pending", False)

    # 提取纯值（兼容 validated_slots 格式）
    pure_slots = {}
    for k, v in slots.items():
        if isinstance(v, dict) and "value" in v:
            pure_slots[k] = v["value"]
        else:
            pure_slots[k] = v

    # ─── 二次确认流程 ───
    if confirm_pending:
        last_msg = state["messages"][-1].content if state.get("messages") else ""

        if _is_confirm(last_msg):
            logger.info("客人已确认，风控放行")
            return {
                "need_clarify": False,
                "confirm_pending": False,
                "decision_trace": (state.get("decision_trace") or []) + [{
                    "step": "risk_checker",
                    "result": "pass",
                    "message": "客人已二次确认，放行",
                }],
            }

        if _is_cancel(last_msg):
            logger.info("客人取消操作")
            return {
                "need_clarify": True,
                "confirm_pending": False,
                "decision_trace": (state.get("decision_trace") or []) + [{
                    "step": "risk_checker",
                    "result": "cancelled",
                    "message": "客人取消操作",
                }],
            }

        # 客人说了别的话（不是确认也不是取消），保持等待确认状态
        logger.info("等待确认中，客人消息非确认/取消: %s", last_msg[:40])
        return {"need_clarify": True}

    # ─── 首次进入：执行风控检查 ───
    if not intents:
        logger.info("risk_checker: 无意图，跳过")
        return {}

    result = check_risks(intents, pure_slots, entities, state)

    existing_traces = state.get("decision_trace") or []

    if result["passed"]:
        return {
            "need_clarify": False,
            "decision_trace": existing_traces + result["traces"],
        }

    if result["need_confirm"]:
        logger.info("风控: 需要二次确认 — %s", result["primary_reason"])
        confirm_action = result.get("confirm_action", {})
        summary = confirm_action.get("summary", "此操作")
        room = confirm_action.get("room", "")

        from langchain_core.messages import AIMessage
        room = confirm_action.get("room", "")
        loc = f"到{room}房间" if room else ""
        # ★ 让 LLM 生成自然的确认话术
        try:
            from langchain_openai import ChatOpenAI
            _llm = ChatOpenAI(
                model="deepseek-chat", temperature=0.5,
                api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
                base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            )
            c_prompt = (
                f"你是五星级酒店客房管家。\n"
                f"请用自然口语跟客人确认：{summary}，房间：{room or '待确认'}。\n"
                f"要亲切温和，简短，不要生硬。直接输出确认文本。"
            )
            llm_r = _llm.invoke([SystemMessage(content=c_prompt)])
            confirm_text = llm_r.content.strip() if llm_r.content else f"我跟您确认一下：{summary}{loc}，没问题吧？"
        except Exception:
            confirm_text = f"确认一下：{summary}{loc}，对吗？"
        confirm_msg = AIMessage(content=confirm_text)

        return {
            "messages": [confirm_msg],
            "need_clarify": True,
            "confirm_pending": True,
            "confirm_action": confirm_action,
            "decision_trace": existing_traces + result["traces"],
        }

    # 非确认型拦截（如 low_confidence）
    from langchain_core.messages import AIMessage
    return {
        "messages": [AIMessage(
            content="抱歉，我无法确定您的意图，能再说一遍吗？"
        )],
        "need_clarify": True,
        "decision_trace": existing_traces + result["traces"],
    }


# ============================================================
# 第六部分: 自测
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("risk_checker.py 自测")
    print("=" * 60)

    # Test 1: 高风险意图 → 需二次确认
    print("\n[Test 1] HOUSEKEEPING 高风险 → 需二次确认")
    intents = [{"L1": "HOUSEKEEPING", "id": "SVC_HK_001", "score": 0.95}]
    slots = {"request_type": "housekeeping", "location": "301"}
    result = check_risks(intents, slots, {}, {})
    assert result["passed"] is False
    assert result["need_confirm"] is True
    assert result["primary_reason"] == "risky_action_need_confirm"
    print(f"  PASS: need_confirm=True, reason={result['primary_reason']}")

    # Test 2: ALARM set → 不需要确认
    print("\n[Test 2] ALARM set → 不需要确认")
    intents = [{"L1": "ALARM", "id": "ALARM_001", "score": 0.95}]
    slots = {"time": "07:00", "duration": 60}
    result = check_risks(intents, slots, {}, {})
    assert result["passed"] is True
    print(f"  PASS: passed=True (ALARM set 无需确认)")

    # Test 3: ALARM delete → 需要确认
    print("\n[Test 3] ALARM delete → 需要确认")
    intents = [{"L1": "ALARM", "id": "ALARM_002", "score": 0.95}]
    slots = {"alarm_action": "delete", "label": "起床闹钟"}
    result = check_risks(intents, slots, {}, {})
    assert result["passed"] is False
    assert result["need_confirm"] is True
    print(f"  PASS: need_confirm=True (ALARM delete 需要确认)")

    # Test 4: ROOM_SERVICE 高风险 → 需确认
    print("\n[Test 4] ROOM_SERVICE 高风险 → 需确认")
    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}]
    slots = {"request_type": "amenity", "location": "301", "details": "两瓶矿泉水"}
    result = check_risks(intents, slots, {}, {})
    assert result["passed"] is False
    assert result["need_confirm"] is True
    print(f"  PASS: need_confirm=True, confirm_action={result['confirm_action']}")

    # Test 5: 低置信度 → 触发 GR-09
    print("\n[Test 5] 低置信度 → 触发 GR-09")
    intents = [{"L1": "HOUSEKEEPING", "id": "SVC_HK_001", "score": 0.3}]  # 低于 0.5
    slots = {"request_type": "housekeeping", "location": "301"}
    result = check_risks(intents, slots, {}, {})
    # 应该同时触发 intent_risk + GR-09
    assert result["passed"] is False
    assert len(result["triggered_rules"]) >= 2
    print(f"  PASS: 触发 {len(result['triggered_rules'])} 条红线, 主={result['primary_reason']}")

    # Test 6: 什么都不触发
    print("\n[Test 6] 无风险操作 → 全部通过")
    # ALARM set 且 score 高
    intents = [{"L1": "ALARM", "id": "ALARM_001", "score": 0.95}]
    slots = {"time": "07:00", "duration": 60}
    result = check_risks(intents, slots, {}, {})
    assert result["passed"] is True
    print(f"  PASS: passed=True")

    # Test 7: 确认关键词检测
    print("\n[Test 7] 确认/取消关键词检测")
    assert _is_confirm("确认") is True
    assert _is_confirm("好的") is True
    assert _is_confirm("行") is True
    assert _is_confirm("随便聊聊") is False
    assert _is_cancel("算了") is True
    assert _is_cancel("不用了谢谢") is True
    assert _is_cancel("取消") is True
    assert _is_cancel("继续") is False
    print("  PASS: 确认/取消关键词检测正确")

    print("\n" + "=" * 60)
    print("全部自测通过! risk_checker.py 就绪。")
    print("=" * 60)
