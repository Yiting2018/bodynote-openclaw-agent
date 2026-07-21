from __future__ import annotations

import re

from bodynote_agent.handlers.contracts import HandlerResult, result


def parse_meal(text: str) -> HandlerResult | None:
    if not any(marker in text for marker in ("吃了", "喝了", "早餐", "早饭", "午餐", "午饭", "晚餐", "晚饭", "加餐", "夜宵", "照旧", "固定餐")):
        return None
    aliases = ((("早餐", "早饭", "早上"), "breakfast"), (("午餐", "午饭", "中午"), "lunch"), (("晚餐", "晚饭", "晚上"), "dinner"), (("加餐", "夜宵"), "snack"))
    meal_type = next((value for markers, value in aliases if any(marker in text for marker in markers)), None)
    content_match = re.search(r"(?:吃了|喝了|吃|喝)\s*(.+)", text)
    content = content_match.group(1) if content_match else text
    content = re.split(r"(?:，|,)?\s*(?:感觉|心情|然后|之后)", content, maxsplit=1)[0]
    foods = []
    for item in re.split(r"[、，,和+]", content):
        cleaned = re.sub(r"^(?:今天|昨天|早餐|早饭|午餐|午饭|晚餐|晚饭|加餐|夜宵)", "", item.strip(" 。.!！")).strip()
        if cleaned and cleaned not in {"吃了", "喝了", "吃", "喝"}:
            foods.append(cleaned)
    payload = {"foods": foods}
    if meal_type:
        payload["meal_type"] = meal_type
    for key, label in (("calories_kcal", r"(\d{2,4})\s*(?:千卡|kcal|大卡)"), ("protein_g", r"蛋白质?\s*[:：]?\s*(\d+(?:\.\d+)?)\s*g"), ("carbs_g", r"(?:碳水|碳水化合物)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*g"), ("fat_g", r"脂肪\s*[:：]?\s*(\d+(?:\.\d+)?)\s*g")):
        match = re.search(label, text, re.I)
        if match:
            payload[key] = float(match.group(1)) if key != "calories_kcal" else int(match.group(1))
    follow_up = None if meal_type else "这是早餐、午餐、晚餐还是加餐？不补也可以，日报会标记为餐次未知。"
    return result("meal", payload, 0.88 if meal_type and foods else 0.7,
                  required_fields=("foods",), follow_up=follow_up,
                  ambiguities=("meal_type",) if meal_type is None else ())
