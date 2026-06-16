"""
酒店客房服务 Tool 函数集 (Function Calling)
==============================================
Day 8 改造:
  - 全部工具返回结构化 dict（含 status / intent_id / request_type / message / trace）
  - 新增 request_type 参数（与 BRD SL_039 枚举对齐）
  - 新增 3 个缺失工具: call_hotel / delete_alarm / close_alarm

工具 ↔ BRD Intent 映射:
  request_supplies    → SVC_ROOM_001 (ROOM_SERVICE, amenity)
  request_cleaning    → SVC_HK_001  (HOUSEKEEPING, housekeeping)
  report_maintenance  → SVC_HK_001  (HOUSEKEEPING, workorder)
  request_laundry     → SVC_HK_001  (HOUSEKEEPING, amenity)
  call_hotel          → SVC_CALL_001 (HOTEL_CALL, hotel_call)
  set_wake_up_call    → ALARM_001   (ALARM, alarm_action=set)
  delete_alarm        → ALARM_002   (ALARM, alarm_action=delete)
  close_alarm         → ALARM_003   (ALARM, alarm_action=close)
"""
from typing import Optional

from langchain_core.tools import tool


def _check_room(room_number: str) -> Optional[str]:
    """
    校验房间号是否有效。如果无效，返回错误信息；有效则返回 None。

    无效情况：空、N/A、过长（>6）、纯字母、看起来像 LLM 编的。
    """
    if not room_number or not room_number.strip():
        return "错误：缺少房间号。请先向客人确认房间号后再调用此工具。"
    room = room_number.strip()
    if room.upper() == "N/A":
        return "错误：房间号未知。请先向客人确认房间号后再调用此工具。"
    if len(room) > 6:
        return f"错误：房间号 '{room}' 格式异常（过长）。请向客人确认正确的房间号。"
    if not any(c.isdigit() for c in room):
        return f"错误：房间号 '{room}' 不含数字，可能不正确。请向客人确认。"
    # 纯数字 3-4 位 或 字母+数字（如 F301、A1206）都合法
    return None


def _ok(intent_id: str, request_type: str, room_number: str,
        message: str, tool_name: str, **extra) -> dict:
    """统一成功响应格式"""
    result = {
        "status": "success",
        "intent_id": intent_id,
        "request_type": request_type,
        "room_number": room_number,
        "message": message,
        "trace": {
            "tool": tool_name,
            "intent_id": intent_id,
            "request_type": request_type,
        },
    }
    result.update(extra)
    return result


# ============================================================
# 服务类工具（device_type = service）
# ============================================================

@tool
def request_supplies(room_number: str, item: str, quantity: int = 1,
                     request_type: str = "amenity") -> dict:
    """送物品到房间。客人要毛巾/矿泉水/牙刷/拖鞋等消耗品时调用。room_number=房号, item=物品名, quantity=数量(默认1)"""
    err = _check_room(room_number)
    if err:
        return {"status": "error", "message": err}
    return _ok(
        intent_id="SVC_ROOM_001",
        request_type=request_type,
        room_number=room_number,
        message=f"已安排为房间 {room_number} 配送 {quantity}份{item}，客房服务员将在10分钟内送达。",
        tool_name="request_supplies",
        item=item,
        quantity=quantity,
    )


@tool
def request_cleaning(room_number: str, time_preference: str = "现在",
                     request_type: str = "housekeeping") -> dict:
    """预约打扫房间。客人要打扫/做卫生/收拾房间时调用。room_number=房号, time_preference=打扫时间(默认现在)"""
    err = _check_room(room_number)
    if err:
        return {"status": "error", "message": err}
    return _ok(
        intent_id="SVC_HK_001",
        request_type=request_type,
        room_number=room_number,
        message=f"已安排保洁部在 {time_preference} 为房间 {room_number} 进行打扫。保洁员到达前会电话确认。",
        tool_name="request_cleaning",
        time_preference=time_preference,
    )


@tool
def report_maintenance(room_number: str, issue: str, urgency: str = "normal",
                       request_type: str = "workorder") -> dict:
    """报修设备。灯泡/空调/马桶/WiFi/电视/淋浴等故障时调用。room_number=房号, issue=故障描述, urgency=normal或urgent"""
    eta = "马上" if urgency == "urgent" else "2小时"
    err = _check_room(room_number)
    if err:
        return {"status": "error", "message": err}
    return _ok(
        intent_id="SVC_HK_001",
        request_type=request_type,
        room_number=room_number,
        message=f"已经记录下来了，{room_number}房间的{issue}问题，维修师傅{'优先处理，' + eta + '内到' if urgency == 'urgent' else eta + '内到'}。",
        tool_name="report_maintenance",
        issue=issue,
        urgency=urgency,
    )


@tool
def request_laundry(room_number: str, items: str, pickup_time: str = "现在",
                    request_type: str = "amenity") -> dict:
    """安排洗衣/干洗/熨烫。room_number=房号, items=衣物描述, pickup_time=取衣时间(默认现在)"""
    err = _check_room(room_number)
    if err:
        return {"status": "error", "message": err}
    return _ok(
        intent_id="SVC_HK_001",
        request_type=request_type,
        room_number=room_number,
        message=f"已为房间 {room_number} 安排洗衣服务。待洗衣物：{items}。服务员将在{pickup_time}上门取件。普通洗衣4小时内送回，干洗/熨烫6小时内送回。",
        tool_name="request_laundry",
        items=items,
        pickup_time=pickup_time,
    )


@tool
def call_hotel(room_number: str = "",
               request_type: str = "hotel_call") -> dict:
    """呼叫前台/转接人工。客人要叫前台/联系工作人员时调用。room_number=房号(可选)"""
    loc = f"房间 {room_number}" if room_number else "您"
    return _ok(
        intent_id="SVC_CALL_001",
        request_type=request_type,
        room_number=room_number or "N/A",
        message=f"已为{loc}转接前台。工作人员将尽快与您联系。如需即时服务请拨打前台电话（0000）。",
        tool_name="call_hotel",
    )


# ============================================================
# 叫醒/闹钟类工具（device_type = alarm）
# ============================================================

@tool
def set_wake_up_call(room_number: str, time: str) -> dict:
    """设置叫醒/闹钟。room_number=房号, time=叫醒时间(如7:00)"""
    err = _check_room(room_number)
    if err:
        return {"status": "error", "message": err}
    return _ok(
        intent_id="ALARM_001",
        request_type="alarm_set",
        room_number=room_number,
        message=f"已为房间 {room_number} 设置唤醒服务，时间：{time}。届时电话将自动振铃，如未接听将转人工确认。",
        tool_name="set_wake_up_call",
        time=time,
    )


@tool
def delete_alarm(label: str, room_number: str = "", alarm_id: str = "") -> dict:
    """删除/取消闹钟。⚠️高风险：必须先向客人确认后再调用。label=闹钟名, room_number=房号(可选)"""
    target = f"'{label}'" if label else (f"ID={alarm_id}" if alarm_id else "指定闹钟")
    loc = f"房间 {room_number}" if room_number else "您的房间"
    return _ok(
        intent_id="ALARM_002",
        request_type="alarm_delete",
        room_number=room_number or "N/A",
        message=f"已为{loc}取消闹钟 {target}。如需重新设置请随时告知。",
        tool_name="delete_alarm",
        label=label,
        alarm_id=alarm_id,
    )


@tool
def close_alarm(room_number: str = "", label: str = "") -> dict:
    """关闭正在响的闹钟。⚠️高风险：必须先向客人确认后再调用。room_number=房号(可选), label=闹钟名(可选)"""
    target = f"闹钟 '{label}'" if label else "闹钟"
    loc = f"房间 {room_number}" if room_number else "您的房间"
    return _ok(
        intent_id="ALARM_003",
        request_type="alarm_close",
        room_number=room_number or "N/A",
        message=f"已为{loc}关闭{target}。",
        tool_name="close_alarm",
        label=label,
    )


# ============================================================
# 工具列表汇总
# ============================================================

ALL_TOOLS = [
    request_supplies,
    request_cleaning,
    report_maintenance,
    request_laundry,
    call_hotel,
    set_wake_up_call,
    delete_alarm,
    close_alarm,
]
