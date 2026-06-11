# tools_api/ — 工具函数（Agent 的"手"）

---

## 这个文件夹是干什么的？

用一句话理解：**这里定义了 Agent 能"实际执行"的所有动作。**

Agent 不是一个只会说话的聊天机器人——它通过 Tool Calling 机制调用这里的函数来"做事"：送东西、叫保洁、报维修、设闹钟。这些函数目前是 mock 实现（模拟返回结果），将来会替换成真实的酒店 PMS 系统调用。

---

## 工具调用流程（Day 8 版本）

```
客人说："送两瓶水到301"
  → chatbot: JSON 分析 → ROOM_SERVICE
  → slot_validator: 槽位校验通过
  → capability_gate: service 支持 ROOM_SERVICE ✅
  → risk_checker: 高风险需确认 → "为了您的安全，需要确认..."
  （客人回复"确认"后）
  → risk_checker: 已确认，放行
  → tool_executor: determine_tool() → request_supplies
  → request_supplies.invoke({room_number: "301", item: "矿泉水", quantity: 2})
  → 返回结构化 dict → 转为 AIMessage 回复客人
```

---

## 8 个工具函数完整清单

### 服务类（device_type = service）

| # | 函数 | Intent ID | request_type | 触发场景 |
|---|------|-----------|-------------|---------|
| 1 | `request_supplies` | SVC_ROOM_001 | amenity | "送两瓶水""拿条毛巾""给我牙刷" |
| 2 | `request_cleaning` | SVC_HK_001 | housekeeping | "打扫一下房间""做卫生" |
| 3 | `report_maintenance` | SVC_HK_001 | workorder | "空调不制冷""灯泡坏了""WiFi连不上" |
| 4 | `request_laundry` | SVC_HK_001 | amenity | "帮我洗两件衬衫""西装干洗" |
| 5 | `call_hotel` | SVC_CALL_001 | hotel_call | "帮我转人工""叫前台过来" |

### 叫醒/闹钟类（device_type = alarm）

| # | 函数 | Intent ID | alarm_action | 触发场景 |
|---|------|-----------|-------------|---------|
| 6 | `set_wake_up_call` | ALARM_001 | set | "7点叫我""明天早上六点半叫醒" |
| 7 | `delete_alarm` | ALARM_002 | delete | "取消闹钟""删掉7点的闹钟" ⚠️ 需确认 |
| 8 | `close_alarm` | ALARM_003 | close | "关掉闹钟""停止响铃" ⚠️ 需确认 |

---

## 统一返回值格式（Day 8 改造后）

所有工具返回统一的 dict 结构：

```python
{
    "status": "success",           # 执行状态
    "intent_id": "SVC_ROOM_001",   # BRD 意图 ID
    "request_type": "amenity",     # BRD SL_039 枚举值
    "room_number": "301",          # 房间号
    "message": "已安排配送...",     # 人可读通知
    "trace": {                     # 结构化追溯
        "tool": "request_supplies",
        "intent_id": "SVC_ROOM_001",
        "request_type": "amenity"
    },
    # 工具特有字段
    "item": "矿泉水",
    "quantity": 2
}
```

**与改造前的区别**：

| | 改造前 | 改造后 |
|---|--------|--------|
| 返回值 | 纯文本字符串 | 结构化 dict（含 trace） |
| request_type 参数 | 无 | 每个工具都有，与 BRD SL_039 对齐 |
| 可追溯性 | 无 | trace 含 tool/intent_id/request_type |

---

## 工具 ↔ BRD Intent 映射总表

```
ROOM_SERVICE (SVC_ROOM_001) ──→ request_supplies    (amenity)

HOUSEKEEPING (SVC_HK_001)  ──→ request_cleaning     (housekeeping)
                           ├──→ report_maintenance   (workorder)
                           └──→ request_laundry      (amenity)

HOTEL_CALL (SVC_CALL_001)  ──→ call_hotel           (hotel_call)

ALARM (ALARM_001) SETTINGS ──→ set_wake_up_call
ALARM (ALARM_002) DELETE   ──→ delete_alarm
ALARM (ALARM_003) CLOSE    ──→ close_alarm
```

---

## 如何新增一个工具

假设要加"代客泊车"：

```python
@tool
def valet_parking(room_number: str, request_type: str = "other") -> dict:
    """
    为客人安排代客泊车服务。

    Args:
        room_number: 房间号
        request_type: 服务类型，默认 other
    """
    return _ok(
        intent_id="SVC_ROOM_001",
        request_type=request_type,
        room_number=room_number,
        message=f"已为房间 {room_number} 安排代客泊车。",
        tool_name="valet_parking",
    )

# 加到 ALL_TOOLS 列表
ALL_TOOLS.append(valet_parking)
```

然后在 `room_service_agent.py` 的 `INTENT_TO_TOOL` 和 `determine_tool()` 中添加路由逻辑。

---

## 文件状态

| 状态 | 工具 | 说明 |
|------|------|------|
| ✅ Day 8 改造 | request_supplies | 加 request_type + dict 返回 |
| ✅ Day 8 改造 | request_cleaning | 加 request_type + dict 返回 |
| ✅ Day 8 改造 | report_maintenance | 加 request_type + dict 返回 |
| ✅ Day 8 改造 | request_laundry | 加 request_type + dict 返回 |
| ✅ Day 8 改造 | set_wake_up_call | 改为 dict 返回 |
| ✅ Day 8 新增 | call_hotel | 对应 SVC_CALL_001 |
| ✅ Day 8 新增 | delete_alarm | 对应 ALARM_002（需二次确认） |
| ✅ Day 8 新增 | close_alarm | 对应 ALARM_003（需二次确认） |
