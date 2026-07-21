from __future__ import annotations

import re

from bodynote_agent.handlers.contracts import HandlerResult, result


def parse_exercise(text: str) -> HandlerResult | None:
    step_match = re.search(r"(\d{2,6})\s*步", text)
    markers = ("跑步", "走了", "快走", "运动", "训练", "健身", "骑行", "骑车", "游泳", "拉伸", "瑜伽", "椭圆机", "练胸", "练背", "练腿", "练肩", "深蹲", "硬拉")
    if not step_match and not any(marker in text for marker in markers):
        return None
    activity_map = (("跑步", "running"), ("快走", "brisk_walking"), ("骑行", "cycling"), ("骑车", "cycling"), ("游泳", "swimming"), ("椭圆机", "elliptical"), ("拉伸", "stretching"), ("瑜伽", "yoga"))
    activity = next((value for marker, value in activity_map if marker in text), None)
    payload = {"activity": activity or ("walking" if step_match or "走了" in text else "strength_training")}
    if step_match:
        payload["steps"] = int(step_match.group(1))
    duration = duration_minutes(text)
    if duration is not None:
        payload["duration_min"] = duration
    distance = re.search(r"(\d+(?:\.\d+)?)\s*(?:公里|km)", text, re.I)
    if distance:
        payload["distance_km"] = float(distance.group(1))
    calories = re.search(r"(?:消耗|燃烧)\s*(\d{2,4})\s*(?:千卡|kcal|卡)", text, re.I)
    if calories:
        payload["calories_kcal"] = int(calories.group(1))
    heart_rate = re.search(r"(?:平均)?心率\s*[:：]?\s*(\d{2,3})", text)
    if heart_rate:
        payload["avg_heart_rate_bpm"] = int(heart_rate.group(1))
    body_parts = [label for marker, label in (("胸", "chest"), ("背", "back"), ("腿", "legs"), ("臀", "glutes"), ("肩", "shoulders"), ("核心", "core"), ("腹", "core")) if marker in text]
    if body_parts:
        payload["body_parts"] = list(dict.fromkeys(body_parts))
    return result("exercise", payload, 0.9 if len(payload) > 1 else 0.72,
                  required_fields=("activity",))


def duration_minutes(text: str) -> int | None:
    total = 0
    for value, unit in re.findall(r"(\d+(?:\.\d+)?|一|二|两|三)\s*(小时|个小时|分钟|min)", text, re.I):
        number = {"一": 1.0, "二": 2.0, "两": 2.0, "三": 3.0}.get(value, float(value) if value.replace(".", "", 1).isdigit() else 0)
        total += round(number * 60) if "小时" in unit else round(number)
    return total or None
