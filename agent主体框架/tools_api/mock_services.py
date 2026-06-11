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
from langchain_core.tools import tool


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
    """
    为客人补充房间消耗品。当客人要求送毛巾、牙刷、矿泉水、拖鞋、纸巾、沐浴露等物品时使用。

    常见物品：毛巾、浴巾、牙刷、牙膏、梳子、浴帽、剃须刀、拖鞋、矿泉水、纸巾、卫生纸、沐浴露、洗发水、护发素、润肤露、香皂、被子、枕头、衣架

    Args:
        room_number: 房间号，例如 "301"
        item: 客人需要的物品名称
        quantity: 数量，默认1
        request_type: 服务类型，默认 amenity（来自 BRD SL_039 枚举）

    Returns:
        结构化配送确认
    """
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
    """
    为客人预约客房清洁服务。当客人要求打扫房间、做卫生、收拾房间时使用。

    Args:
        room_number: 房间号，例如 "301"
        time_preference: 客人希望打扫的时间，例如 "现在"、"下午2点"
        request_type: 服务类型，默认 housekeeping

    Returns:
        结构化保洁确认
    """
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
    """
    受理客人房间设备报修。当客人反映灯泡坏了、空调不制冷/制热、马桶堵塞、WiFi连不上、电视故障、淋浴没热水等问题时使用。

    Args:
        room_number: 房间号，例如 "301"
        issue: 故障描述，例如 "空调不制冷"、"马桶堵塞"
        urgency: 紧急程度，normal（普通）或 urgent（紧急），默认 normal
        request_type: 服务类型，默认 workorder

    Returns:
        结构化维修工单确认
    """
    urgency_text = "紧急" if urgency == "urgent" else "普通"
    eta = "马上" if urgency == "urgent" else "2小时"
    emoji = "🔧" if urgency != "urgent" else ""
    return _ok(
        intent_id="SVC_HK_001",
        request_type=request_type,
        room_number=room_number,
        message=f"已经记录下来了{emoji}，{room_number}房间的{issue}问题，维修师傅{'优先处理，' + eta + '内到' if urgency == 'urgent' else eta + '内到'}。",
        tool_name="report_maintenance",
        issue=issue,
        urgency=urgency,
    )


@tool
def request_laundry(room_number: str, items: str, pickup_time: str = "现在",
                    request_type: str = "amenity") -> dict:
    """
    为客人安排洗衣/干洗服务。当客人需要洗衣、干洗、熨烫服务时使用。

    Args:
        room_number: 房间号，例如 "301"
        items: 待洗衣物描述，例如 "两件衬衫和一条西裤"、"一套西装需要干洗"
        pickup_time: 取衣时间，默认 "现在"
        request_type: 服务类型，默认 amenity

    Returns:
        结构化洗衣服务确认
    """
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
    """
    为客人呼叫酒店前台/转接人工服务。当客人要求叫前台、转人工、联系工作人员时使用。

    Args:
        room_number: 房间号（可选），例如 "301"
        request_type: 服务类型，默认 hotel_call

    Returns:
        结构化呼叫确认
    """
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
    """
    为客人设置叫醒/唤醒服务（Morning Call）。当客人需要设定叫醒时间时使用。

    Args:
        room_number: 房间号，例如 "301"
        time: 叫醒时间，例如 "7:00"、"早上六点半"

    Returns:
        结构化唤醒服务确认
    """
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
    """
    删除/取消闹钟。当客人要求取消闹钟、删除叫醒时使用。

    ⚠️ 高风险操作：必须经客人二次确认后才调用。

    Args:
        label: 闹钟标签/名称，例如 "起床闹钟"
        room_number: 房间号（可选）
        alarm_id: 闹钟ID（可选，精确删除用）

    Returns:
        结构化删除确认
    """
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
    """
    关闭正在响的闹钟。当客人要求停止闹钟、关掉响铃时使用。

    ⚠️ 高风险操作：必须经客人二次确认后才调用。

    Args:
        room_number: 房间号（可选）
        label: 闹钟标签（可选），例如 "起床闹钟"

    Returns:
        结构化关闭确认
    """
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
