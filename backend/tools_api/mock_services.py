"""
Hotel Room Service Tool Functions (Function Calling)
==============================================
Day 8 refactor:
  - All tools return structured dict (with status / intent_id / request_type / message / trace)
  - Added request_type parameter (aligned with BRD SL_039 enum)
  - Added 3 missing tools: call_hotel / delete_alarm / close_alarm

Tool ↔ BRD Intent mapping:
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
    """Unified success response format"""
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
# Service tools (device_type = service)
# ============================================================

@tool
def request_supplies(room_number: str, item: str, quantity: int = 1,
                     request_type: str = "amenity") -> dict:
    """
    Replenish room consumables for a guest. Use when the guest asks for towels, toothbrushes,
    water bottles, slippers, tissues, shower gel, and similar items.

    Common items: towel, bath towel, toothbrush, toothpaste, comb, shower cap, razor, slippers,
    water bottle, tissues, toilet paper, shower gel, shampoo, conditioner, body lotion, soap,
    blanket, pillow, hanger

    Args:
        room_number: Room number, e.g. "301"
        item: Name of the item the guest needs
        quantity: Quantity, default 1
        request_type: Service type, default amenity (from BRD SL_039 enum)

    Returns:
        Structured delivery confirmation
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
    Schedule room cleaning for a guest. Use when the guest asks for room cleaning,
    tidying up, or housekeeping.

    Args:
        room_number: Room number, e.g. "301"
        time_preference: When the guest wants cleaning, e.g. "现在" (now), "下午2点" (2pm)
        request_type: Service type, default housekeeping

    Returns:
        Structured cleaning confirmation
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
    Handle equipment maintenance reports. Use when the guest reports a broken light bulb,
    AC not cooling/heating, clogged toilet, WiFi not connecting, TV malfunction,
    shower no hot water, and similar issues.

    Args:
        room_number: Room number, e.g. "301"
        issue: Fault description, e.g. "空调不制冷" (AC not cooling), "马桶堵塞" (clogged toilet)
        urgency: Urgency level — "normal" or "urgent", default "normal"
        request_type: Service type, default workorder

    Returns:
        Structured maintenance work order confirmation
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
    Arrange laundry / dry cleaning for a guest. Use when the guest needs laundry,
    dry cleaning, or ironing services.

    Args:
        room_number: Room number, e.g. "301"
        items: Description of laundry items, e.g. "两件衬衫和一条西裤" (two shirts and trousers)
        pickup_time: Pickup time, default "现在" (now)
        request_type: Service type, default amenity

    Returns:
        Structured laundry service confirmation
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
    Call the hotel front desk / transfer to human staff. Use when the guest asks
    to reach the front desk, speak to a human, or contact staff.

    Args:
        room_number: Room number (optional), e.g. "301"
        request_type: Service type, default hotel_call

    Returns:
        Structured call confirmation
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
# Wake-up / alarm tools (device_type = alarm)
# ============================================================

@tool
def set_wake_up_call(room_number: str, time: str) -> dict:
    """
    Set a wake-up / morning call for a guest. Use when the guest wants to set a wake-up time.

    Args:
        room_number: Room number, e.g. "301"
        time: Wake-up time, e.g. "7:00", "早上六点半" (6:30am)

    Returns:
        Structured wake-up service confirmation
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
    Delete / cancel an alarm. Use when the guest asks to cancel an alarm or delete a wake-up call.

    ⚠️ HIGH-RISK operation: MUST obtain explicit guest confirmation before calling.

    Args:
        label: Alarm label / name, e.g. "起床闹钟" (wake-up alarm)
        room_number: Room number (optional)
        alarm_id: Alarm ID (optional, for precise deletion)

    Returns:
        Structured deletion confirmation
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
    Dismiss a ringing alarm. Use when the guest asks to stop an alarm or turn off a ringing bell.

    ⚠️ HIGH-RISK operation: MUST obtain explicit guest confirmation before calling.

    Args:
        room_number: Room number (optional)
        label: Alarm label (optional), e.g. "起床闹钟" (wake-up alarm)

    Returns:
        Structured close confirmation
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
# Tool list summary
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
