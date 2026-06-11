"""
locale_resolver.py — 语言检测与回退节点
=========================================
BRD 对齐: §10.1 枚举治理（language 表）/ §9 步骤1

检测用户输入的语言，不做复杂 NLP——用简单规则匹配。
检测不到时回退到默认语言 zh-CN，标记 locale_missing_defaulted。
"""

import os
import json
import re
import logging
from typing import Optional

logger = logging.getLogger("LocaleResolver")

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

_lang_config: Optional[dict] = None


def _load_config():
    global _lang_config
    if _lang_config is not None:
        return
    with open(os.path.join(_CONFIG_DIR, "general.json"), "r", encoding="utf-8") as f:
        _lang_config = json.load(f).get("language", {})
    logger.info("语言检测器初始化: 支持 %s, 默认 %s",
                _lang_config.get("enum", []), _lang_config.get("default", "zh-CN"))


# ============================================================
# 检测规则
# ============================================================

# 每种语言的特征词（高置信度信号）
LANG_SIGNALS = {
    "en-US": {
        "words": ["please", "thank", "hello", "room", "water", "towels", "clean",
                   "help", "morning", "call", "need", "want", "can", "could", "would"],
        "weight": 2,
    },
    "en-SG": {
        "words": ["lah", "lor", "leh", "can or not", "how ah", "like that"],
        "weight": 3,
    },
    "zh-GD": {
        "words": ["唔該", "乜嘢", "係邊", "點解", "呢個", "嗰個", "有冇", "啱唔啱",
                   "咗", "嘅", "啲", "喺", "嚟"],
        "weight": 3,
    },
    "zh-CN": {
        "words": [],  # 兜底，不设特征词
        "weight": 1,
    },
}

# 纯中文字符比例阈值
CN_CHAR_RATIO = 0.3


def _detect_locale(text: str) -> tuple:
    """
    检测文本的语言。

    Returns:
        (locale_code, confidence, method)
        method: "signal" | "char_ratio" | "default"
    """
    text_lower = text.lower().strip()

    # 1. 高置信度信号匹配
    best_locale = None
    best_score = 0

    for locale, cfg in LANG_SIGNALS.items():
        if locale == "zh-CN":
            continue  # zh-CN 不用特征词匹配
        score = 0
        for word in cfg["words"]:
            if word in text_lower:
                score += cfg["weight"]
        if score > best_score:
            best_score = score
            best_locale = locale

    if best_locale and best_score >= 3:
        return (best_locale, min(1.0, best_score / 6), "signal")

    # 2. 中文字符比例检测
    cn_chars = len(re.findall(r'[一-鿿]', text))
    total_chars = len(re.sub(r'\s', '', text))
    if total_chars > 0 and cn_chars / total_chars >= CN_CHAR_RATIO:
        return ("zh-CN", 0.7, "char_ratio")

    # 3. 纯英文/拉丁字符 → en-US
    latin_chars = len(re.findall(r'[a-zA-Z]', text))
    if total_chars > 0 and latin_chars / total_chars >= 0.5:
        return ("en-US", 0.5, "char_ratio")

    # 4. 兜底
    return (_get_default(), 0.1, "default")


def _get_default() -> str:
    _load_config()
    return _lang_config.get("default", "zh-CN")


def _validate_locale(locale: str) -> str:
    """确保 locale 在合法枚举中，否则回退默认"""
    _load_config()
    allowed = _lang_config.get("enum", [])
    if locale in allowed:
        return locale
    return _get_default()


# ============================================================
# 主入口
# ============================================================

def resolve_locale(text: str) -> dict:
    """
    Args:
        text: 用户消息文本

    Returns:
        {
            "locale": "zh-CN",
            "confidence": 0.7,
            "method": "char_ratio",
            "defaulted": False,
            "trace": {...}
        }
    """
    _load_config()

    locale, confidence, method = _detect_locale(text)
    locale = _validate_locale(locale)
    defaulted = (method == "default")

    trace = {
        "step": "locale_resolver",
        "result": "defaulted" if defaulted else "pass",
        "locale": locale,
        "method": method,
        "confidence": confidence,
    }

    if defaulted:
        logger.info("语言检测: 回退默认 %s", locale)
        trace["reason_code"] = "locale_missing_defaulted"
    else:
        logger.info("语言检测: %s (confidence=%.2f, method=%s)", locale, confidence, method)

    return {
        "locale": locale,
        "confidence": confidence,
        "method": method,
        "defaulted": defaulted,
        "trace": trace,
    }


# ============================================================
# LangGraph 节点
# ============================================================

def locale_resolver_node(state: dict) -> dict:
    """LangGraph 节点：语言检测"""
    messages = state.get("messages") or []
    if not messages:
        return {"locale": _get_default()}

    text = messages[-1].content if hasattr(messages[-1], "content") else str(messages[-1])
    result = resolve_locale(text)

    existing_traces = state.get("decision_trace") or []
    trace = result.get("trace", {})

    return {
        "locale": result["locale"],
        "decision_trace": existing_traces + ([trace] if trace else []),
    }


# ============================================================
# 自测
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("locale_resolver.py 自测")
    print("=" * 60)

    tests = [
        ("帮我送两瓶水到301", "zh-CN", "中文"),
        ("please send two bottles of water to room 301", "en-US", "英文"),
        ("唔該送兩支水去301", "zh-GD", "粤语"),
        ("can or not send water to 301 ah", "en-SG", "新加坡英语"),
        ("hello", "en-US", "简单英文"),
        ("你好", "zh-CN", "简单中文"),
        ("", "zh-CN", "空字符串 → 默认"),
    ]

    for text, expected, desc in tests:
        result = resolve_locale(text)
        status = "PASS" if result["locale"] == expected else f"FAIL (got {result['locale']})"
        print(f"  [{status}] {desc}: '{text[:40]}' → {result['locale']} (method={result['method']})")

    print("\n全部自测完成! locale_resolver.py 就绪。")
