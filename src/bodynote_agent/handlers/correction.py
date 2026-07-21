from __future__ import annotations

import re

from bodynote_agent.handlers.contracts import CorrectionCommand


def parse_correction(text: str) -> CorrectionCommand | None:
    correction_markers = ("修正", "更正", "改成", "说错了", "记错了", "删除刚才", "删掉刚才", "撤销刚才", "删除上一条", "删掉上一条")
    if not any(marker in text for marker in correction_markers) and not ("那顿" in text and "不是" in text):
        return None
    if any(marker in text for marker in ("删除", "删掉", "撤销")):
        return CorrectionCommand("delete")
    patch = {}
    target = None
    if any(marker in text for marker in ("睡眠", "睡觉", "入睡")):
        target = "sleep"
    elif any(marker in text for marker in ("那顿", "餐", "下午茶")):
        target = "meal"
    weight = re.search(r"(?:体重)?(?:改成|是|为)\s*(\d{2,3}(?:\.\d+)?)\s*(kg|公斤|斤)?", text, re.I)
    if weight and ("体重" in text or "kg" in text.lower() or "公斤" in text or "斤" in text):
        value = float(weight.group(1))
        patch["weight_kg"] = round(value / 2, 2) if weight.group(2) == "斤" else value
        target = "body"
    steps = re.search(r"(?:改成|是|为)?\s*(\d{2,6})\s*步", text)
    if steps:
        patch["steps"] = int(steps.group(1))
        target = "exercise"
    sleep = re.search(r"(?:改成|是|为)?\s*(\d+(?:\.\d+)?)\s*(?:个)?小时", text)
    if sleep and any(marker in text for marker in ("睡", "睡眠")):
        patch["duration_hours"] = float(sleep.group(1))
        target = "sleep"
    replacement_text = re.split(r"(?:改成|更正为|是)", text)[-1]
    for markers, value in ((("早餐", "早饭"), "breakfast"), (("午餐", "午饭"), "lunch"), (("晚餐", "晚饭"), "dinner"), (("下午茶", "加餐", "夜宵"), "snack")):
        if any(marker in replacement_text for marker in markers):
            patch["meal_type"] = value
            target = "meal"
            break
    occurred_at_text = text if any(marker in text for marker in ("昨天", "前天", "今早", "昨晚", "点", "时", ":", "：")) else None
    ambiguities = () if patch or occurred_at_text else ("correction_field",)
    return CorrectionCommand("update", target, patch, occurred_at_text, 0.92 if not ambiguities else 0.55, ambiguities)
