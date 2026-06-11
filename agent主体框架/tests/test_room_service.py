"""
test_room_service.py — 客房服务 Agent AC1~AC5 验收测试
========================================================
BRD §11 验收标准:
  AC1: 输出枚举值闭环
  AC2: 能力矩阵严格生效
  AC3: 槽位范围与 clamp 生效
  AC4: 缺失 required 槽位必进入 need_clarify
  AC5: 实体/动作命中可追溯

运行方式: python llm/tests/test_room_service.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
logging.basicConfig(level=logging.ERROR, force=True)


# ============================================================
# AC1: 输出枚举值闭环
# ============================================================

def test_ac1_enum_valid():
    """合法枚举值应通过校验"""
    from core.slot_validator import validate_slots

    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}]
    slots = {"request_type": "amenity", "location": "301", "details": "矿泉水"}

    result = validate_slots(slots, intents)
    assert result["need_clarify"] is False, f"Expected pass, got {result['blocking_reason']}"
    assert result["validated_slots"]["request_type"]["status"] == "valid"
    print("  [AC1-1 PASS] 合法枚举: request_type=amenity → valid")


def test_ac1_enum_invalid():
    """非法枚举值应触发 invalid_enum"""
    from core.slot_validator import validate_slots

    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}]
    slots = {"request_type": "唱歌", "location": "301"}

    result = validate_slots(slots, intents)
    assert result["need_clarify"] is True
    assert result["validated_slots"]["request_type"]["status"] == "invalid"
    print("  [AC1-2 PASS] 非法枚举: request_type='唱歌' → invalid")


def test_ac1_priority_defaulted():
    """未指定 priority 应自动补 normal"""
    from core.slot_validator import validate_slots

    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}]
    slots = {"request_type": "amenity", "location": "301"}

    result = validate_slots(slots, intents)
    assert result["validated_slots"]["priority"]["status"] == "defaulted"
    assert result["validated_slots"]["priority"]["value"] == "normal"
    print("  [AC1-3 PASS] 默认值: priority → normal (defaulted)")


# ============================================================
# AC2: 能力矩阵严格生效
# ============================================================

def test_ac2_service_supports_room_service():
    """service 设备应支持 ROOM_SERVICE"""
    from core.capability_gate import check_capability

    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001"}]
    result = check_capability(intents)
    assert result["passed"] is True
    print("  [AC2-1 PASS] service 支持 ROOM_SERVICE")


def test_ac2_alarm_supports_alarm():
    """alarm 设备应支持 ALARM"""
    from core.capability_gate import check_capability

    intents = [{"L1": "ALARM", "id": "ALARM_001"}]
    result = check_capability(intents)
    assert result["passed"] is True
    assert result["device_type"] == "alarm"
    print("  [AC2-2 PASS] alarm 支持 ALARM")


def test_ac2_unknown_intent_blocked():
    """未知意图应被拦截"""
    from core.capability_gate import check_capability

    intents = [{"L1": "UNKNOWN_INTENT", "id": ""}]
    result = check_capability(intents)
    assert result["passed"] is False
    print("  [AC2-3 PASS] 未知意图 → 拦截")


# ============================================================
# AC3: 槽位范围与 clamp 生效
# ============================================================

def test_ac3_duration_clamped():
    """duration 超出范围应 clamp"""
    from core.slot_validator import validate_slots

    intents = [{"L1": "ALARM", "id": "ALARM_001", "score": 0.95}]
    slots = {"time": "07:00", "duration": 50000}

    result = validate_slots(slots, intents)
    assert result["validated_slots"]["duration"]["status"] == "clamped"
    assert result["validated_slots"]["duration"]["value"] == 10080.0
    print("  [AC3-1 PASS] duration 50000 → clamp 到 10080")


def test_ac3_duration_valid():
    """duration 在范围内应通过"""
    from core.slot_validator import validate_slots

    intents = [{"L1": "ALARM", "id": "ALARM_001", "score": 0.95}]
    slots = {"time": "07:00", "duration": 60}

    result = validate_slots(slots, intents)
    assert result["validated_slots"]["duration"]["status"] == "valid"
    print("  [AC3-2 PASS] duration 60 → valid")


def test_ac3_duration_default():
    """duration 未指定应有默认值"""
    from core.slot_validator import validate_slots

    intents = [{"L1": "ALARM", "id": "ALARM_001", "score": 0.95}]
    slots = {"time": "07:00"}

    result = validate_slots(slots, intents)
    assert result["validated_slots"]["duration"]["status"] == "defaulted"
    assert result["validated_slots"]["duration"]["value"] == 60
    print("  [AC3-3 PASS] duration 未填 → defaulted=60")


# ============================================================
# AC4: 缺失 required 槽位必进入 need_clarify
# ============================================================

def test_ac4_missing_request_type():
    """缺少 request_type（ROOM_SERVICE 的 required 槽位）"""
    from core.slot_validator import validate_slots

    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}]
    slots = {"location": "301"}

    result = validate_slots(slots, intents)
    assert result["need_clarify"] is True
    assert "request_type" in result["blocking_reason"]
    print("  [AC4-1 PASS] 缺 request_type → need_clarify")


def test_ac4_missing_time():
    """ALARM_001 缺 time"""
    from core.slot_validator import validate_slots

    intents = [{"L1": "ALARM", "id": "ALARM_001", "score": 0.95}]
    slots = {"duration": 60}

    result = validate_slots(slots, intents)
    assert result["need_clarify"] is True
    assert "time" in result["blocking_reason"]
    print("  [AC4-2 PASS] ALARM 缺 time → need_clarify")


def test_ac4_all_slots_present():
    """所有 required 槽位都存在 → 通过"""
    from core.slot_validator import validate_slots

    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}]
    slots = {"request_type": "amenity", "location": "301", "details": "矿泉水"}

    result = validate_slots(slots, intents)
    assert result["need_clarify"] is False
    print("  [AC4-3 PASS] 全部槽位齐全 → pass")


# ============================================================
# AC5: 实体/动作命中可追溯
# ============================================================

def test_ac5_trace_contains_validation_steps():
    """decision_trace 应包含各校验节点的记录"""
    from core.slot_validator import validate_slots
    from core.capability_gate import check_capability

    # 1. slot_validator trace
    intents = [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}]
    slots = {"request_type": "amenity", "location": "301", "details": "矿泉水"}
    result = validate_slots(slots, intents)
    traces = result["traces"]
    assert any(t["step"] == "slot_validator" for t in traces)
    assert any(t.get("slot") == "request_type" for t in traces)
    print("  [AC5-1 PASS] slot_validator trace 包含校验记录")

    # 2. capability_gate trace
    result2 = check_capability(intents)
    trace2 = result2.get("trace", {})
    assert trace2.get("step") == "capability_gate"
    assert trace2.get("result") == "pass"
    print("  [AC5-2 PASS] capability_gate trace 可追溯")


def test_ac5_entity_resolution_trace():
    """实体解析应有 trace"""
    from core.entity_resolver import resolve_entities
    from langchain_core.messages import HumanMessage

    state = {
        "raw_intents": [{"L1": "ROOM_SERVICE"}],
        "raw_entities": {"room": "301", "item": "矿泉水"},
        "raw_slots": {"location": "301"},
        "messages": [HumanMessage(content="送水到301")],
    }
    result = resolve_entities(state)
    trace = result.get("trace", {})
    assert trace.get("step") == "entity_resolver"
    assert trace.get("result") == "pass"
    print("  [AC5-3 PASS] entity_resolver trace 可追溯")


def test_ac5_risk_checker_trace():
    """风控检查应有 trace"""
    from core.risk_checker import check_risks

    intents = [{"L1": "HOUSEKEEPING", "id": "SVC_HK_001", "score": 0.95}]
    slots = {"request_type": "housekeeping", "location": "301"}
    result = check_risks(intents, slots, {}, {})
    traces = result["traces"]
    assert len(traces) > 0
    assert traces[0]["step"] == "risk_checker"
    print("  [AC5-4 PASS] risk_checker trace 可追溯")


# ============================================================
# 额外测试
# ============================================================

def test_risk_confirm_flow():
    """二次确认流程：高风险 → 拦截 → 确认 → 放行"""
    from core.risk_checker import check_risks, _is_confirm, _is_cancel

    # 首次：高风险应拦截
    intents = [{"L1": "HOUSEKEEPING", "id": "SVC_HK_001", "score": 0.95}]
    slots = {"request_type": "housekeeping", "location": "301"}
    result = check_risks(intents, slots, {}, {})
    assert result["passed"] is False
    assert result["need_confirm"] is True
    print("  [EXTRA-1 PASS] 高风险意图 → 需要二次确认")

    # 确认关键词
    assert _is_confirm("确认") is True
    assert _is_confirm("好的") is True
    assert _is_cancel("算了") is True
    assert _is_cancel("不用了") is True
    print("  [EXTRA-2 PASS] 确认/取消关键词检测正确")


def test_clarify_builder():
    """澄清追问构建：缺槽位 → 追问消息"""
    from core.clarify_builder import build_clarify

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
    assert len(result["message"]) > 0
    print(f"  [EXTRA-3 PASS] clarify_builder 生成追问: {result['message'][:50]}...")


def test_response_formatter():
    """最终输出格式化"""
    from core.response_formatter import format_response
    from langchain_core.messages import AIMessage

    state = {
        "is_safe": "SAFE",
        "need_clarify": False,
        "raw_intents": [{"L1": "ROOM_SERVICE", "id": "SVC_ROOM_001", "score": 0.95}],
        "validated_slots": {"request_type": {"value": "amenity", "status": "valid"}},
        "raw_entities": {"room": "301"},
        "decision_trace": [{"step": "slot_validator", "result": "pass"}],
        "messages": [AIMessage(content="已安排配送。")],
    }
    result = format_response(state)
    assert result["result_type"] == "execute"
    assert result["structured_output"]["final_intent"]["L1"] == "ROOM_SERVICE"
    assert len(result["structured_output"]["decision_trace"]) >= 2
    print("  [EXTRA-4 PASS] response_formatter 输出 execute 格式正确")


# ============================================================
# 运行全部
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  客房服务 Agent — AC1~AC5 验收测试")
    print("=" * 60)

    tests = [
        # AC1: 枚举闭环
        test_ac1_enum_valid,
        test_ac1_enum_invalid,
        test_ac1_priority_defaulted,
        # AC2: 能力矩阵
        test_ac2_service_supports_room_service,
        test_ac2_alarm_supports_alarm,
        test_ac2_unknown_intent_blocked,
        # AC3: 槽位范围
        test_ac3_duration_clamped,
        test_ac3_duration_valid,
        test_ac3_duration_default,
        # AC4: required 检查
        test_ac4_missing_request_type,
        test_ac4_missing_time,
        test_ac4_all_slots_present,
        # AC5: 可追溯
        test_ac5_trace_contains_validation_steps,
        test_ac5_entity_resolution_trace,
        test_ac5_risk_checker_trace,
        # 额外
        test_risk_confirm_flow,
        test_clarify_builder,
        test_response_formatter,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"  ❌ FAIL: {test.__name__} — {e}")
        except Exception as e:
            failed += 1
            print(f"  ❌ ERROR: {test.__name__} — {e}")

    print(f"\n{'=' * 60}")
    print(f"  结果: {passed} PASS, {failed} FAIL (共 {len(tests)} 个测试)")
    print(f"{'=' * 60}")

    if failed > 0:
        sys.exit(1)
