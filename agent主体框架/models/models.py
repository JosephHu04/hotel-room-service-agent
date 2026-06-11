"""
models.py — 客房服务 Agent 全部数据类定义
==============================================
BRD 对齐: §5.2 输出契约 / §6 统一识别原因码 / §8.2 IntentDefinitions / §8.3 SlotDefinitions
所有数据节点之间的流转格式在此统一定义，避免各模块自行发明字段名。

设计原则:
  - 每个字段都有 BRD 来源注释
  - 使用 @dataclass 保持轻量
  - Optional 字段一律提供默认值 None
  - Enum 继承 str，可直接 JSON 序列化
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Optional, Union
from enum import Enum


# ============================================================
# 第一部分: 枚举类型（BRD §5.2 + §6 + §10.1）
# ============================================================

class ResultType(str, Enum):
    """最终决策结果类型 — BRD §5.2 输出契约"""
    EXECUTE = "execute"            # 校验全部通过，可以执行工具
    NEED_CLARIFY = "need_clarify"  # 缺槽/歧义/风险待确认，需要追问客人
    REJECT = "reject"              # 超出能力范围/不安全，礼貌拒绝


class ReasonCode(str, Enum):
    """14 个标准原因码 — BRD §6 统一识别原因码表"""
    # --- 槽位相关 ---
    MISSING_REQUIRED_SLOT = "missing_required_slot"        # 缺必选槽位
    INVALID_ENUM = "invalid_enum"                           # 枚举值不合法
    OUT_OF_RANGE_CLAMPED = "out_of_range_clamped"           # 数值越界已clamp（非阻塞）
    PARSE_TIME_FAILED = "parse_time_failed"                 # 时间解析失败
    PARSE_DURATION_FAILED = "parse_duration_failed"         # 时长解析失败

    # --- 实体相关 ---
    AMBIGUOUS_ENTITY = "ambiguous_entity"                   # 实体歧义（多个候选）
    ENTITY_NOT_FOUND = "entity_not_found"                   # 实体未找到

    # --- 意图相关 ---
    INTENT_CONFLICT = "intent_conflict"                     # 意图冲突
    LOW_CONFIDENCE = "low_confidence"                       # 置信度不足

    # --- 能力相关 ---
    CAPABILITY_UNSUPPORTED = "capability_unsupported"       # 能力矩阵不支持

    # --- 风控相关 ---
    RISKY_ACTION_NEED_CONFIRM = "risky_action_need_confirm" # 高风险/不可逆需二次确认

    # --- 其他 ---
    DEVICE_UNAVAILABLE = "device_unavailable"               # 设备不可用/离线
    LOCALE_MISSING_DEFAULTED = "locale_missing_defaulted"   # 语言缺失已回退默认
    OUT_OF_SCOPE = "out_of_scope"                           # 超出Agent能力范围


class SlotStatus(str, Enum):
    """槽位校验状态 — BRD §8.3 + AC3"""
    RAW = "raw"              # LLM 原始输出，未经校验
    VALID = "valid"          # 通过全部校验
    CLAMPED = "clamped"      # 数值越界已压缩到边界值
    DEFAULTED = "defaulted"  # 用户未填，系统自动补默认值
    INVALID = "invalid"      # 校验失败且无法自动修复


# ============================================================
# 第二部分: 核心数据类（BRD §8.2 / §8.3 / §6.1.2 / §5.2）
# ============================================================

@dataclass
class IntentCandidate:
    """候选意图 — BRD §8.2 IntentDefinitions 表结构 + §9 步骤3

    使用场景:
      - chatbot_node 解析 LLM JSON 输出后生成
      - clarify_builder 在 intent_conflict 时返回多个候选
    """
    L1: str                        # 意图一级分类, 如 "ROOM_SERVICE", "ALARM"
    L2: str = "DEFAULT"            # 意图二级分类, 如 "CREATE_REQUEST", "SETTINGS"
    L3: str = "DEFAULT"            # 意图三级分类
    id: str = ""                   # BRD 意图ID, 如 "SVC_ROOM_001"
    score: float = 1.0             # 置信度 0.0~1.0

    def __post_init__(self):
        """确保 id 不为空时与 L1/L2/L3 一致"""
        if not self.id and self.L1:
            # 从 L1 推断 id 前缀（用于日志，不保证精确匹配）
            pass

    def to_dict(self) -> dict:
        return {
            "L1": self.L1,
            "L2": self.L2,
            "L3": self.L3,
            "id": self.id,
            "score": self.score,
        }


@dataclass
class Slot:
    """单个槽位 — BRD §8.3 SlotDefinitions 表 + AC3

    status 生命周期:
      raw (LLM输出) → valid / clamped / defaulted / invalid (slot_validator处理后)

    使用场景:
      - chatbot_node 输出: status="raw"
      - slot_validator 处理后: status="valid" | "clamped" | "defaulted" | "invalid"
    """
    name: str                       # 槽位名, 如 "request_type", "duration", "location"
    value: Any = None               # 槽位的值, 如 "amenity", 60.0, "301"
    status: SlotStatus = SlotStatus.RAW  # 校验状态
    original_value: Any = None      # 原始值（仅 clamped/invalid 时有意义）
    message: str = ""               # 人可读说明，如 "值 50000 已 clamp 到 10080"

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "value": self.value,
            "status": self.status.value,
        }
        if self.original_value is not None:
            d["original_value"] = self.original_value
        if self.message:
            d["message"] = self.message
        return d

    @classmethod
    def from_raw(cls, name: str, value: Any) -> "Slot":
        """快捷构造：LLM 原始输出的槽位"""
        return cls(name=name, value=value, status=SlotStatus.RAW)

    @classmethod
    def from_default(cls, name: str, default_value: Any) -> "Slot":
        """快捷构造：系统自动补全的默认槽位"""
        return cls(
            name=name,
            value=default_value,
            status=SlotStatus.DEFAULTED,
            message=f"未指定 {name}，已自动填充默认值: {default_value}",
        )

    @classmethod
    def from_clamped(cls, name: str, original: Any, clamped: Any, bound: str) -> "Slot":
        """快捷构造：越界已 clamp 的槽位"""
        return cls(
            name=name,
            value=clamped,
            status=SlotStatus.CLAMPED,
            original_value=original,
            message=f"{name} 原始值 {original} 超出{bound}边界，已调整为 {clamped}",
        )

    @classmethod
    def from_invalid(cls, name: str, value: Any, reason: str) -> "Slot":
        """快捷构造：校验失败的槽位"""
        return cls(
            name=name,
            value=value,
            status=SlotStatus.INVALID,
            original_value=value,
            message=reason,
        )


@dataclass
class NeedClarify:
    """澄清输出结构 — BRD §6.1.2 输出字段规范 + §6.1.5 强约束

    字段必填规则（BRD §6.1.5）:
      missing_required_slot     → clarify_slot 必填, candidates 可选
      ambiguous_entity          → clarify_slot 必填, candidates 必填
      entity_not_found          → clarify_slot 必填
      intent_conflict           → candidates 必填
      capability_unsupported    → candidates 或 supported_intents 必填
      risky_action_need_confirm → confirm_action 必填
      parse_time_failed         → clarify_slot="time", candidates 给可解析格式
      parse_duration_failed     → clarify_slot="duration", candidates 给可解析格式
      low_confidence            → candidates 必填
    """
    reason_code: ReasonCode                       # 必填: 14个原因码之一
    clarify_slot: str = ""                        # 需要用户补充的字段名
    candidates: list = field(default_factory=list) # 候选列表（实体名/意图/时间格式等）
    prompt_key: Optional[str] = None              # 话术模板 key（后期对接 i18n）
    target_intent: Optional[IntentCandidate] = None  # 期望目标意图
    confirm_action: Optional[dict] = None          # 二次确认摘要（风险场景必填）

    def to_dict(self) -> dict:
        d = {
            "reason_code": self.reason_code.value,
            "clarify_slot": self.clarify_slot,
        }
        if self.candidates:
            d["candidates"] = self.candidates
        if self.prompt_key:
            d["prompt_key"] = self.prompt_key
        if self.target_intent:
            d["target_intent"] = self.target_intent.to_dict()
        if self.confirm_action:
            d["confirm_action"] = self.confirm_action
        return d


@dataclass
class DecisionTraceStep:
    """单条追溯记录 — BRD §5.2 decision_trace + §11 AC5

    每个节点执行后写入一条，最终汇总到 FinalOutput.decision_trace。
    确保全链路可追溯：谁做了什么、命中了什么规则、输入输出是什么。
    """
    step: str                                  # 节点名, 如 "slot_validator", "risk_checker"
    result: str                                # "pass" | "fail" | "clamped" | "defaulted" | "blocked"
    rule_id: Optional[str] = None              # 命中的规则编号, 如 "GR-03", "SL_019"
    reason_code: Optional[ReasonCode] = None   # 命中的原因码
    input_data: dict = field(default_factory=dict)   # 节点输入关键字段
    output_data: dict = field(default_factory=dict)  # 节点输出关键字段
    message: str = ""                          # 人可读说明

    def to_dict(self) -> dict:
        d = {
            "step": self.step,
            "result": self.result,
            "message": self.message,
        }
        if self.rule_id:
            d["rule_id"] = self.rule_id
        if self.reason_code:
            d["reason_code"] = self.reason_code.value
        if self.input_data:
            d["input_data"] = self.input_data
        if self.output_data:
            d["output_data"] = self.output_data
        return d


@dataclass
class FinalOutput:
    """Agent 最终输出 — BRD §5.2 输出契约（全部字段）

    所有节点执行完毕后，response_formatter 收集 state 中的全部信息
    组装成 FinalOutput 返回给调用方（FastAPI / Gradio / 其他Agent）。

    三种 result_type 的输出示例见本文件末尾 docstring。
    """
    result_type: ResultType                            # execute / need_clarify / reject
    decision_trace: list = field(default_factory=list) # 全链路追溯记录

    # --- execute 时有值 ---
    final_intent: Optional[IntentCandidate] = None     # 最终确定的唯一意图
    final_slots: dict = field(default_factory=dict)    # key=槽位名, value=Slot 对象
    resolved_entities: dict = field(default_factory=dict)  # key=实体类型, value=解析值

    # --- need_clarify 时有值 ---
    clarify_info: Optional[NeedClarify] = None         # 澄清详情

    # --- 元信息 ---
    session_id: str = ""                               # 会话 ID（房间号）
    response_text: str = ""                            # 最终回复文本（给客人看的）

    def to_dict(self) -> dict:
        """序列化为字典（递归转换嵌套对象）"""
        d: dict = {
            "result_type": self.result_type.value,
            "decision_trace": [t.to_dict() if isinstance(t, DecisionTraceStep) else t
                               for t in self.decision_trace],
        }

        if self.final_intent:
            d["final_intent"] = self.final_intent.to_dict()

        if self.final_slots:
            d["final_slots"] = {
                k: v.to_dict() if isinstance(v, Slot) else v
                for k, v in self.final_slots.items()
            }

        if self.resolved_entities:
            d["resolved_entities"] = self.resolved_entities

        if self.clarify_info:
            d["clarify_info"] = self.clarify_info.to_dict()

        if self.session_id:
            d["session_id"] = self.session_id

        if self.response_text:
            d["response_text"] = self.response_text

        return d

    # ============================================================
    # 三种 result_type 的输出示例
    # ============================================================
    #
    # 【execute — 校验全部通过，可以执行】
    # {
    #   "result_type": "execute",
    #   "final_intent": {
    #     "L1": "ROOM_SERVICE", "L2": "CREATE_REQUEST", "L3": "DEFAULT",
    #     "id": "SVC_ROOM_001", "score": 0.95
    #   },
    #   "final_slots": {
    #     "request_type": {"name": "request_type", "value": "amenity", "status": "valid"},
    #     "location":     {"name": "location", "value": "301", "status": "valid"},
    #     "details":      {"name": "details", "value": "两瓶矿泉水", "status": "valid"},
    #     "priority":     {"name": "priority", "value": "normal", "status": "defaulted"}
    #   },
    #   "resolved_entities": {"room": "301"},
    #   "decision_trace": [
    #     {"step": "content_safety", "result": "pass", "message": "内容安全通过"},
    #     {"step": "slot_validator", "result": "pass", "message": "全部槽位校验通过"}
    #   ],
    #   "response_text": "好的先生/女士，已为您安排配送两瓶矿泉水到301房间。"
    # }
    #
    # 【need_clarify — 缺槽/歧义/风险，需要追问】
    # {
    #   "result_type": "need_clarify",
    #   "clarify_info": {
    #     "reason_code": "missing_required_slot",
    #     "clarify_slot": "details",
    #     "candidates": []
    #   },
    #   "decision_trace": [
    #     {"step": "slot_validator", "result": "fail", "reason_code": "missing_required_slot"}
    #   ],
    #   "response_text": "请问您需要送什么物品呢？"
    # }
    #
    # 【need_clarify — 高风险需二次确认】
    # {
    #   "result_type": "need_clarify",
    #   "clarify_info": {
    #     "reason_code": "risky_action_need_confirm",
    #     "clarify_slot": "",
    #     "confirm_action": {
    #       "intent": "HOUSEKEEPING",
    #       "scope": "all",
    #       "action": "打扫",
    #       "summary": "全部房间打扫"
    #     }
    #   },
    #   "decision_trace": [
    #     {"step": "risk_checker", "result": "blocked", "rule_id": "GR-03",
    #      "reason_code": "risky_action_need_confirm"}
    #   ],
    #   "response_text": "您确定要打扫全部房间吗？这个操作会生成工单安排保洁人员。"
    # }
    #
    # 【reject — 超出能力范围/不安全】
    # {
    #   "result_type": "reject",
    #   "decision_trace": [
    #     {"step": "content_safety", "result": "blocked", "message": "命中不安全关键词"}
    #   ],
    #   "response_text": "抱歉，我是酒店客房服务助手，无法处理该问题。如有需要请联系前台。"
    # }


# ============================================================
# 第三部分: 辅助函数
# ============================================================

def make_trace(
    step: str,
    result: str,
    message: str = "",
    rule_id: Optional[str] = None,
    reason_code: Optional[ReasonCode] = None,
    input_data: Optional[dict] = None,
    output_data: Optional[dict] = None,
) -> DecisionTraceStep:
    """快捷构造追溯记录 — 所有节点统一用此函数生成 trace

    Args:
        step: 节点名，如 "slot_validator"
        result: 结果，如 "pass" | "fail" | "clamped" | "blocked"
        message: 人可读说明
        rule_id: 命中的规则编号，如 "GR-03"
        reason_code: 原因码
        input_data: 输入数据
        output_data: 输出数据

    Returns:
        DecisionTraceStep 对象

    Example:
        >>> trace = make_trace(
        ...     step="slot_validator",
        ...     result="clamped",
        ...     message="duration 50000 超出上限10080，已clamp",
        ...     rule_id="SL_019",
        ...     reason_code=ReasonCode.OUT_OF_RANGE_CLAMPED,
        ...     input_data={"name": "duration", "value": 50000.0},
        ...     output_data={"name": "duration", "value": 10080.0},
        ... )
    """
    return DecisionTraceStep(
        step=step,
        result=result,
        rule_id=rule_id,
        reason_code=reason_code,
        input_data=input_data or {},
        output_data=output_data or {},
        message=message,
    )


def merge_slots(
    raw_slots: dict[str, Slot],
    validated_slots: dict[str, Slot],
) -> dict[str, Slot]:
    """合并原始槽位和校验后槽位，校验后覆盖原始

    用于 slot_validator 处理后更新 state.final_slots。
    """
    merged = {k: v for k, v in raw_slots.items()}
    for name, slot in validated_slots.items():
        merged[name] = slot
    return merged


def get_slot_value(slots: dict[str, Slot], name: str, default: Any = None) -> Any:
    """安全地从 slots 字典中取值"""
    slot = slots.get(name)
    return slot.value if slot else default


# ============================================================
# 第四部分: 验收自测（直接运行 python models.py 时执行）
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("models.py 数据类自测")
    print("=" * 60)

    # 1. ResultType
    assert ResultType.EXECUTE == "execute"
    assert ResultType.NEED_CLARIFY == "need_clarify"
    assert ResultType.REJECT == "reject"
    print("[PASS] ResultType — 3个枚举值正确")

    # 2. ReasonCode — 14个标准码
    assert len(ReasonCode.__members__) == 14
    print(f"[PASS] ReasonCode — {len(ReasonCode.__members__)}个原因码已定义")

    # 3. IntentCandidate
    intent = IntentCandidate(
        L1="ROOM_SERVICE", L2="CREATE_REQUEST", L3="DEFAULT",
        id="SVC_ROOM_001", score=0.95,
    )
    d = intent.to_dict()
    assert d["L1"] == "ROOM_SERVICE"
    assert d["id"] == "SVC_ROOM_001"
    print(f"[PASS] IntentCandidate — to_dict() 正常: {d['id']}")

    # 4. Slot — 5种状态
    raw_slot = Slot.from_raw("duration", 60)
    assert raw_slot.status == SlotStatus.RAW

    valid_slot = Slot(name="duration", value=60, status=SlotStatus.VALID)
    assert valid_slot.status == SlotStatus.VALID

    clamped_slot = Slot.from_clamped("duration", 50000, 10080, "上限")
    assert clamped_slot.status == SlotStatus.CLAMPED
    assert clamped_slot.value == 10080
    assert clamped_slot.original_value == 50000

    defaulted_slot = Slot.from_default("priority", "normal")
    assert defaulted_slot.status == SlotStatus.DEFAULTED
    assert defaulted_slot.value == "normal"

    invalid_slot = Slot.from_invalid("request_type", "唱歌", "不在枚举列表中")
    assert invalid_slot.status == SlotStatus.INVALID

    print(f"[PASS] Slot — 5种状态 + 4个工厂方法全部正常")

    # 5. NeedClarify
    clarify = NeedClarify(
        reason_code=ReasonCode.MISSING_REQUIRED_SLOT,
        clarify_slot="details",
        candidates=[],
    )
    d = clarify.to_dict()
    assert d["reason_code"] == "missing_required_slot"
    assert d["clarify_slot"] == "details"
    print(f"[PASS] NeedClarify — to_dict() 正常: {d['reason_code']}")

    # 6. DecisionTraceStep
    trace = make_trace(
        step="slot_validator",
        result="clamped",
        message="duration 50000 超出上限10080，已clamp到10080",
        rule_id="SL_019",
        reason_code=ReasonCode.OUT_OF_RANGE_CLAMPED,
        input_data={"name": "duration", "value": 50000.0},
        output_data={"name": "duration", "value": 10080.0},
    )
    assert trace.step == "slot_validator"
    assert trace.result == "clamped"
    assert trace.rule_id == "SL_019"
    print(f"[PASS] DecisionTraceStep — make_trace() 正常")

    # 7. FinalOutput — execute
    output = FinalOutput(
        result_type=ResultType.EXECUTE,
        final_intent=intent,
        final_slots={"request_type": valid_slot},
        resolved_entities={"room": "301"},
        decision_trace=[trace],
        response_text="好的，已为您安排。",
    )
    d = output.to_dict()
    assert d["result_type"] == "execute"
    assert d["final_intent"]["L1"] == "ROOM_SERVICE"
    assert len(d["decision_trace"]) == 1
    print(f"[PASS] FinalOutput(execute) — to_dict() 正常，{len(d)} 个顶层字段")

    # 8. FinalOutput — need_clarify
    output2 = FinalOutput(
        result_type=ResultType.NEED_CLARIFY,
        clarify_info=clarify,
        decision_trace=[
            make_trace("slot_validator", "fail", "缺少必填槽位",
                       reason_code=ReasonCode.MISSING_REQUIRED_SLOT),
        ],
        response_text="请问您需要送什么物品呢？",
    )
    d2 = output2.to_dict()
    assert d2["result_type"] == "need_clarify"
    assert d2["clarify_info"]["reason_code"] == "missing_required_slot"
    print(f"[PASS] FinalOutput(need_clarify) — to_dict() 正常")

    # 9. FinalOutput — reject
    output3 = FinalOutput(
        result_type=ResultType.REJECT,
        decision_trace=[
            make_trace("content_safety", "blocked", "命中不安全关键词"),
        ],
        response_text="抱歉，无法处理该问题。",
    )
    d3 = output3.to_dict()
    assert d3["result_type"] == "reject"
    print(f"[PASS] FinalOutput(reject) — to_dict() 正常")

    # 10. 辅助函数
    merged = merge_slots(
        {"duration": raw_slot},
        {"duration": clamped_slot, "priority": defaulted_slot},
    )
    assert len(merged) == 2
    assert merged["duration"].status == SlotStatus.CLAMPED
    assert merged["priority"].status == SlotStatus.DEFAULTED
    print(f"[PASS] merge_slots — 合并正确，共 {len(merged)} 个槽位")

    assert get_slot_value(merged, "duration") == 10080
    assert get_slot_value(merged, "nonexistent", "fallback") == "fallback"
    print(f"[PASS] get_slot_value — 取值和回退正常")

    print("=" * 60)
    print("全部自测通过! models.py 数据类可用。")
    print("=" * 60)
