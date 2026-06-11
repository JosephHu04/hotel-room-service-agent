"""
prompt_loader.py — 动态加载 System Prompt
===========================================
从 config/ JSON 文件读取意图定义和槽位定义，
自动拼装成 LLM 可理解的 System Prompt。

设计原则:
  - 不硬编码任何意图/槽位信息
  - config JSON 改了什么，prompt 自动同步
  - 生成的 prompt 包含: 角色 + 意图表 + 槽位说明 + JSON输出格式 + 工具铁律 + 安全边界
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger("PromptLoader")

# config/ 目录路径
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")


def _load_json(filename: str) -> dict:
    """加载 config/ 下的 JSON 文件"""
    path = os.path.join(CONFIG_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _format_intent_table(intents: list) -> str:
    """将意图定义格式化为 LLM 易读的表格文本"""
    lines = []
    lines.append("【你可以处理的意图列表】")
    lines.append("-" * 70)

    for item in intents:
        intent_id = item["id"]
        L1 = item["L1"]
        L2 = item["L2"]
        device_type = item["device_type"]
        required = ", ".join(item["required"])
        optional = ", ".join(item.get("optional", [])) or "无"
        description = item.get("description", "")
        risk = item.get("risk_level", "low")
        need_confirm = item.get("require_confirm", False)
        example = item.get("example", "")

        lines.append(f"\n 意图ID: {intent_id}")
        lines.append(f"   分类: {L1} > {L2} > DEFAULT")
        lines.append(f"   设备类型: {device_type}")
        lines.append(f"   说明: {description}")
        lines.append(f"   必填槽位: {required}")
        lines.append(f"   可选槽位: {optional}")
        lines.append(f"   风险等级: {risk}")
        if need_confirm:
            lines.append(f"   ⚠️ 高风险: 执行前必须二次确认！")
        if example:
            lines.append(f"   例句: 「{example}」")

    lines.append("")
    return "\n".join(lines)


def _format_slot_table(slots: list) -> str:
    """将槽位定义格式化为 LLM 易读的说明文本"""
    lines = []
    lines.append("【关键槽位说明】")
    lines.append("-" * 70)

    for s in slots:
        name = s["name"]
        slot_type = s["type"]
        description = s.get("description", "")
        used_by = s.get("used_by_intents", [])

        lines.append(f"\n 槽位: {name}")
        lines.append(f"   类型: {slot_type}")

        if "enum" in s:
            lines.append(f"   可选值: {s['enum']}")

        if "min" in s and "max" in s:
            lines.append(f"   范围: {s['min']} ~ {s['max']} {s.get('unit', '')}")

        if "default" in s:
            lines.append(f"   默认值: {s['default']}（用户未指定时自动填入）")

        if "pattern" in s:
            lines.append(f"   格式: {s.get('pattern_description', s['pattern'])}")

        lines.append(f"   说明: {description}")
        lines.append(f"   用于意图: {used_by}")

    lines.append("")
    return "\n".join(lines)


def _format_tool_rules() -> str:
    """工具调用铁律（从 BRD 和现有工具映射）"""
    return """
【工具调用铁律】
你必须调用对应的工具函数来实际执行，不能只嘴上说"已安排"。

服务类:
  - 送物品(毛巾/水/牙刷/拖鞋等) → 必须调用 request_supplies
  - 打扫房间 → 必须调用 request_cleaning
  - 设备故障(灯/空调/WiFi/马桶等) → 必须调用 report_maintenance
  - 洗衣/干洗/熨烫 → 必须调用 request_laundry
  - 呼叫前台/转接人工 → 必须调用 call_hotel

叫醒/闹钟类:
  - 设定叫醒/闹钟 → 必须调用 set_wake_up_call
  - 删除闹钟 → 必须调用 delete_alarm（⚠️ 需客人二次确认）
  - 关闭正在响的闹钟 → 必须调用 close_alarm（⚠️ 需客人二次确认）

信息补全铁律:
  - 没有房间号就问，绝不自己猜
  - 没有数量就默认 1
  - 没有时间(time)就问，不要猜
  - 没有优先级就默认 normal
  - 缺少必填槽位 → 先追问，再调工具
"""


def _build_json_output_instruction() -> str:
    """JSON 输出格式要求"""
    return """
【输出格式要求 —— 非常重要！】

你必须输出 JSON，同时包含分析结果和给客人的口语回复：

{
  "intents": [
    {
      "L1": "意图一级分类",
      "L2": "意图二级分类",
      "L3": "DEFAULT",
      "id": "意图ID（从可选意图列表中选择）",
      "score": 0.95
    }
  ],
  "slots": {
    "request_type": "提取的值",
    "location": "提取的房间号",
    "details": "提取的详情文本",
    "priority": "提取的优先级",
    "time": "提取的时间",
    "duration": 提取的时长数值,
    "label": "提取的标签",
    "alarm_action": "set/delete/close"
  },
  "entities": {
    "room": "提取的房间号",
    "item": "提取的物品名"
  },
  "reply": "给客人的口语回复（重要！）"
}

关键规则:
  1. intents[] 通常只有1个意图；如果客人只是问候/闲聊/感谢/道别，intents可以为空数组[]
  2. slots 只填实际提取到的，没提取到的不要写
  3. 意图必须从上方列表中选择，不要自己编
  4. ★ reply 必须始终填写！无论是服务请求还是问候闲聊，都要生成自然口语回复：
     - 简短、亲切、有温度
     - 不要用括号、编号、技术术语
     - 如果信息不全，温和地追问（"请问您的房间号是多少呢？"而不是"缺少必填槽位location"）
     - 如果信息齐全，确认并告知客人接下来会发生什么
     - 例："好的，矿泉水马上给您送到301房间，大概10分钟就到。"
     - 例："收到，已经帮您安排打扫302房间了，保洁阿姨一会儿就过去。"
  5. 不要加 Markdown 代码块（```），直接输出 JSON
"""


def load_system_prompt() -> str:
    """加载并组装完整的 System Prompt

    从 config/ JSON 文件动态读取意图和槽位定义，
    拼装到模板中，确保 prompt 与 config 始终一致。

    Returns:
        完整的 system prompt 字符串
    """
    # 1. 读取模板
    template_path = os.path.join(os.path.dirname(__file__), "system_prompt.txt")
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    # 2. 加载配置
    try:
        intents_config = _load_json("intent_definitions.json")
        slots_config = _load_json("slot_definitions.json")
        general_config = _load_json("general.json")
    except FileNotFoundError as e:
        logger.error("配置文件加载失败: %s", e)
        # 回退：不加载动态表，只返回基础模板
        return template

    # 3. 格式化意图和槽位表格
    intent_table = _format_intent_table(intents_config["intents"])
    slot_table = _format_slot_table(slots_config["slots"])
    tool_rules = _format_tool_rules()
    json_instruction = _build_json_output_instruction()

    # 4. 组装
    full_prompt = template
    full_prompt += intent_table
    full_prompt += slot_table
    full_prompt += tool_rules
    full_prompt += json_instruction

    # 5. 补充语言信息
    lang_info = general_config.get("language", {})
    if lang_info:
        langs = ", ".join([
            f"{k}({v})" for k, v in lang_info.get("description", {}).items()
        ])
        full_prompt += f"\n\n【语言设置】\n支持语言: {langs}\n默认语言: {lang_info.get('default', 'zh-CN')}\n"

    return full_prompt


def load_system_prompt_with_rag(rag_context: str = "") -> str:
    """加载 System Prompt 并附加 RAG 检索到的知识上下文

    Args:
        rag_context: RAG 检索到的酒店知识文本

    Returns:
        带知识库上下文的完整 system prompt
    """
    prompt = load_system_prompt()

    if rag_context:
        prompt += f"\n\n【知识库参考（请严格遵守）】\n{rag_context}\n"

    return prompt


# ============================================================
# 自测
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("System Prompt 加载器自测")
    print("=" * 60)

    prompt = load_system_prompt()
    print(f"Prompt 总长度: {len(prompt)} 字符")

    # 验证 6 个必备部分都存在
    checks = [
        ("角色定义", "你是" in prompt),
        ("意图表格", "SVC_ROOM_001" in prompt and "SVC_HK_001" in prompt and "SVC_CALL_001" in prompt),
        ("ALARM意图", "ALARM_001" in prompt and "ALARM_002" in prompt and "ALARM_003" in prompt),
        ("槽位说明", "request_type" in prompt and "duration" in prompt and "location" in prompt),
        ("JSON输出格式", "intents" in prompt and "slots" in prompt),
        ("工具铁律", "request_supplies" in prompt and "set_wake_up_call" in prompt),
        ("安全边界", "酒店服务以外" in prompt or "无法处理" in prompt),
        ("语言设置", "zh-CN" in prompt and "普通话" in prompt),
    ]

    all_pass = True
    for name, result in checks:
        status = "PASS" if result else "FAIL"
        if not result:
            all_pass = False
        print(f"[{status}] {name}")

    if all_pass:
        print("\n全部检查通过! System Prompt 加载器就绪。")
    else:
        print("\n部分检查未通过，请检查 config JSON 文件。")

    # 打印 prompt 预览（前 500 字符）
    print("\n" + "=" * 60)
    print("Prompt 预览（前 500 字符）:")
    print("=" * 60)
    print(prompt[:500])
