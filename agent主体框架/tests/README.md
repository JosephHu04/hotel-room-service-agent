# tests/ — 测试文件

---

## 这个文件夹是干什么的？

用一句话理解：**这里放的是"质检清单"——验证你的 Agent 确实按 BRD 要求做了**。

验收测试 = 模拟客人发消息 → 检查 Agent 返回的 JSON 是否符合 BRD 规定的格式和逻辑。

---

## BRD AC1-AC5 验收标准覆盖

| 验收标准 | BRD 条款 | 测试重点 | 失败示例 |
|---------|---------|---------|---------|
| AC1 | 枚举值闭环 | 所有枚举字段值必须在 config/ 枚举列表中 | request_type="唱歌" 居然通过了 |
| AC2 | 能力矩阵 Gating | 不支持的 intent_L1 不得 execute | light 设备居然执行了 ROOM_SERVICE |
| AC3 | 槽位范围 clamp | 越界值自动 clamp，trace 有标记 | duration=50000 没被 clamp |
| AC4 | 缺失 required 槽 | 缺必填槽 → need_clarify + reason_code + clarify_slot | 缺 request_type 居然直接 execute |
| AC5 | 实体可追溯 | trace 包含命中规则、来源、canonical | 执行了但 trace 是空的 |

---

## 6 条 intent 的测试路径

每条 intent 至少测 2 条路径：

| Intent | 正常路径（execute） | 异常路径（need_clarify/reject） |
|--------|-------------------|-------------------------------|
| ROOM_SERVICE | "送两瓶水到301" | "送一下"（缺item）→ missing_required |
| HOUSEKEEPING | "打扫301" | "全部打扫" （scope=all未确认）→ risky_action |
| HOTEL_CALL | "转接人工" | 首次 → risky_action_need_confirm |
| ALARM set | "7点叫醒我 房号301" | "明天叫我"（缺time）→ parse_time_failed |
| ALARM delete | "取消闹钟 标签起床" | 首次 → risky_action_need_confirm |
| ALARM close | "关掉闹钟" | 首次 → risky_action_need_confirm |

---

## 测试用例模板

```python
def test_room_service_supplies_normal():
    """AC1-5: ROOM_SERVICE正常执行路径"""
    result = invoke_agent("送两瓶矿泉水到301", session_id="test_001")

    # AC1: 枚举闭环
    assert result["final_intent"]["L1"] == "ROOM_SERVICE"
    assert result["final_slots"]["request_type"]["value"] in [
        "room_service", "housekeeping", "hotel_call",
        "workorder", "amenity", "other"
    ]

    # AC4: required槽位不缺
    assert "request_type" in result["final_slots"]

    # AC5: trace可追溯
    assert len(result["decision_trace"]) > 0
    assert any(t["step"] == "slot_validator" for t in result["decision_trace"])

def test_room_service_missing_item():
    """AC4: 缺required槽位 → need_clarify"""
    result = invoke_agent("送一下", session_id="test_002")

    assert result["result_type"] == "need_clarify"
    assert result["clarify_info"]["reason_code"] == "missing_required_slot"
    assert result["clarify_info"]["clarify_slot"] is not None

def test_capability_unsupported():
    """AC2: 能力矩阵gating"""
    # 假设尝试在 light 设备上执行 ROOM_SERVICE
    result = invoke_agent("...", session_id="test_003",
                          device_context={"device_type": "light"})

    assert result["result_type"] in ["need_clarify", "reject"]
    # trace中应有 capability_unsupported 记录
```
